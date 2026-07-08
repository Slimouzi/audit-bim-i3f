"""Audit de présence et de validité des propriétés requises au CCH."""

from __future__ import annotations

from ...domain.ifc_taxonomy import expand_class
from ...extraction.model_data import ModelSnapshot
from ...extraction.normalizer import get_attribute, resolve_value
from ...requirements.models import BIMPhase, RequirementsCatalog
from ..findings import ErrorType, Finding, Severity, Theme
from ..validators import validate_property_value

# Genres de spec audités par présence/valeur ici. ``document`` est traité
# ailleurs (rappel global, pas par élément).
_AUDITED_KINDS = ("property", "quantity")


def _severity_for(spec_kind: str) -> Severity:
    return Severity.MEDIUM if spec_kind in ("property", "quantity") else Severity.LOW


def _missing_meta(spec_kind: str) -> tuple[Theme, Severity, ErrorType]:
    """(thème, sévérité, error_type) d'une **absence** selon le genre de spec.

    Les quantités (BaseQuantities, format 2026) sont regroupées dans le thème
    « Quantités » avec ``SPATIAL_MISSING_QUANTITY`` — même sémantique que le repli
    câblé de ``audit_spatial`` — pour une lecture homogène des livrables (E1)."""
    if spec_kind == "quantity":
        return Theme.QUANTITY, Severity.MEDIUM, ErrorType.SPATIAL_MISSING_QUANTITY
    return Theme.PROPERTY_MISSING, _severity_for(spec_kind), ErrorType.PROPERTY_MISSING


def _invalid_meta(spec_kind: str) -> tuple[Theme, Severity]:
    """(thème, sévérité) d'une **valeur incohérente** selon le genre de spec."""
    if spec_kind == "quantity":
        return Theme.QUANTITY, Severity.MEDIUM
    return Theme.PROPERTY_INVALID, _severity_for(spec_kind)


def _is_empty(value) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    return False


def _property_field_path(ifc_class: str, spec) -> str:
    """``field_path`` structuré d'un défaut de propriété : ``<IfcClass>.<Pset>.<Prop>``
    (chemin composite ``Pset/Prop``) ou ``<IfcClass>.<Attribut>`` (attribut natif).

    Dérivé du **locateur technique** ``pset_or_attribute`` (Pset / attribut natif /
    chemin composite ``Pset/Prop``), jamais du **libellé humain** ``property_name``
    qui peut porter espaces/accents — cf. grammaire gelée (docs/scope-field-path.md).
    """
    # E2 — **jamais** de repli sur ``property_name`` (libellé humain, espaces/accents) :
    # le field_path se dérive du seul locateur technique. Un spec sans locateur est
    # un défaut de catalogue → produit un field_path non grammatical que le verrou
    # attrape (plutôt qu'une chaîne « propre » masquant le défaut).
    locator = (spec.pset_or_attribute or "").strip()
    for sep in ("/", "."):
        if sep in locator:
            pset, prop = locator.split(sep, 1)
            return f"{ifc_class}.{pset.strip()}.{prop.strip()}"
    return f"{ifc_class}.{locator}"


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

    # Classes IFC pour lesquelles le CCH exige des propriétés OU des quantités à
    # cette phase (E1 : les exigences kind="quantity" du format 2026 étaient
    # auparavant ignorées — surfaces/quantités jamais auditées).
    ifc_classes = sorted(
        {
            p.ifc_class
            for p in catalog.properties
            if p.required_at(phase) and p.kind in _AUDITED_KINDS
        }
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
                if spec.kind not in _AUDITED_KINDS:
                    continue
                value = resolve_value(el, spec.pset_or_attribute, spec.property_name)
                via = f" (exigence définie sur {ifc_class})" if actual_class != ifc_class else ""
                if _is_empty(value):
                    miss_theme, miss_sev, miss_err = _missing_meta(spec.kind)
                    findings.append(
                        Finding(
                            theme=miss_theme,
                            severity=miss_sev,
                            error_type=miss_err,
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
                            field_path=_property_field_path(actual_class, spec),
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
                    inv_theme, inv_sev = _invalid_meta(spec.kind)
                    findings.append(
                        Finding(
                            theme=inv_theme,
                            severity=inv_sev,
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
                            field_path=_property_field_path(actual_class, spec),
                        )
                    )
    return _dedup(findings)


def _dedup(findings: list[Finding]) -> list[Finding]:
    """Supprime les findings **strictement identiques** (même objet, même classe,
    même champ, même type d'erreur), en préservant l'ordre.

    Une même exigence peut être listée à la fois sur la classe générique du CCH
    (``IfcWall``) et sur une sous-classe (``IfcWallStandardCase``) : un élément
    ``IfcWallStandardCase`` est alors audité deux fois → deux findings identiques.
    On garde le premier.
    """
    seen: set[tuple] = set()
    out: list[Finding] = []
    for f in findings:
        key = (f.element_uuid, f.ifc_type, f.field_path, f.error_type)
        if key in seen:
            continue
        seen.add(key)
        out.append(f)
    return out
