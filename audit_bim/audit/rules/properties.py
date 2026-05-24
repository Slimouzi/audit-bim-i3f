"""Audit de présence et de validité des propriétés requises au CCH."""

from __future__ import annotations

from ...extraction.model_data import ModelSnapshot
from ...extraction.normalizer import get_attribute, resolve_value
from ...requirements.models import BIMPhase, RequirementsCatalog
from ..findings import ErrorType, Finding, Severity, Theme
from ..ifc_hierarchy import expand_class
from ..validators import validate_property_value


def _severity_for(spec_kind: str) -> Severity:
    return Severity.MEDIUM if spec_kind == "property" else Severity.LOW


def _is_empty(value) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    return False


def audit_properties(
    snap: ModelSnapshot,
    catalog: RequirementsCatalog,
    phase: BIMPhase,
) -> list[Finding]:
    """Pour chaque ``PropertySpec`` requis à la phase, vérifie sa présence.

    On regroupe les exigences par classe IFC pour éviter de scanner les éléments
    inutilement. Les exigences de type ``document`` ne sont pas auditées ici
    (elles sont remontées comme rappel dans le rapport global, pas par élément).
    """
    findings: list[Finding] = []

    # Classes IFC pour lesquelles le CCH exige des propriétés à cette phase
    ifc_classes = sorted(
        {p.ifc_class for p in catalog.properties if p.required_at(phase) and p.kind == "property"}
    )

    for ifc_class in ifc_classes:
        specs = catalog.properties_for(ifc_class, phase)
        if not specs:
            continue
        # Hiérarchie IFC : un parent du CCH (IfcWall) couvre aussi les
        # sous-classes émises par Revit/ArchiCAD (IfcWallStandardCase…).
        target_classes = expand_class(ifc_class)
        elements: list[tuple[str, dict]] = []
        for tc in target_classes:
            for el in snap.of_class(tc):
                elements.append((tc, el))

        if not elements:
            # Aucune instance ni de la classe parente, ni d'aucune sous-classe
            findings.append(
                Finding(
                    theme=Theme.PROPERTY_MISSING,
                    severity=Severity.MEDIUM,
                    error_type=ErrorType.PROPERTY_MISSING,
                    ifc_type=ifc_class,
                    expected=f"≥ 1 instance de {ifc_class} à la phase {phase.value}",
                    actual=0,
                    ref_cch="Chap 6.2",
                    recommended_action=(
                        f"Modéliser au moins une instance de {ifc_class} dans la maquette."
                    ),
                )
            )
            continue

        for actual_class, el in elements:
            uuid = el.get("uuid")
            nm = get_attribute(el, "Name") or el.get("name")
            for spec in specs:
                if spec.kind != "property":
                    continue
                value = resolve_value(el, spec.pset_or_attribute, spec.property_name)
                via = f" (exigence définie sur {ifc_class})" if actual_class != ifc_class else ""
                if _is_empty(value):
                    findings.append(
                        Finding(
                            theme=Theme.PROPERTY_MISSING,
                            severity=_severity_for(spec.kind),
                            error_type=ErrorType.PROPERTY_MISSING,
                            element_uuid=uuid,
                            ifc_type=actual_class,
                            name=nm,
                            expected=(
                                f"{spec.pset_or_attribute or '(attribut natif)'}"
                                f" › {spec.property_name}{via}"
                            ),
                            actual=None,
                            ref_cch=spec.ref_cch,
                            recommended_action=(
                                f"Renseigner {spec.property_name} sur "
                                f"{actual_class} (phase {phase.value})."
                            ),
                        )
                    )
                    continue

                # Valeur présente — on vérifie qu'elle est *cohérente*
                # (numérique positif, booléen, chaîne non vide, plage…).
                reason = validate_property_value(
                    value,
                    property_name=spec.property_name,
                    pset_or_attribute=spec.pset_or_attribute,
                    comment=spec.comment,
                )
                if reason:
                    findings.append(
                        Finding(
                            theme=Theme.PROPERTY_INVALID,
                            severity=_severity_for(spec.kind),
                            error_type=ErrorType.PROPERTY_TYPE_INVALID,
                            element_uuid=uuid,
                            ifc_type=actual_class,
                            name=nm,
                            expected=(
                                f"{spec.pset_or_attribute or '(attribut natif)'}"
                                f" › {spec.property_name} cohérente{via}"
                            ),
                            actual=f"{value!r} — {reason}",
                            ref_cch=spec.ref_cch,
                            recommended_action=(
                                f"Corriger {spec.property_name} sur {actual_class} — {reason}."
                            ),
                        )
                    )
    return findings
