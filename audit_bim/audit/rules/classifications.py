"""Audit des classifications IFC sur les composants.

Les classifications I3F (UniFormat, Omniclass, ou table interne 3F) doivent
être renseignées sur chaque composant physique pour permettre l'exploitation
(GMAO, DOE). On vérifie :
- la *présence* d'au moins une classification,
- la *cohérence* du couple (Code, Source) : si une classification est attachée,
  elle doit avoir une notation/code non vide.
"""
from __future__ import annotations

from ...extraction.model_data import ModelSnapshot
from ...extraction.normalizer import get_attribute
from ...requirements.models import BIMPhase, RequirementsCatalog
from ..findings import ErrorType, Finding, Severity, Theme

# Classes IFC "spatiales / abstraites / de référence" qu'on n'audite PAS :
# pas de classification métier (UniFormat/Omniclass/3F) attendue dessus.
NON_CLASSIFIED_IFC = {
    "IfcProject",
    "IfcSite",
    "IfcBuilding",
    "IfcBuildingStorey",
    "IfcSpace",
    "IfcZone",
    "IfcSystem",
    "IfcGroup",
    "IfcOpeningElement",
    "IfcSpatialZone",
    # Éléments de référence / aide à la modélisation (grilles d'axes,
    # annotations, vides de réservation virtuels) — non classifiables côté MOA.
    "IfcGrid",
    "IfcGridAxis",
    "IfcAnnotation",
}


def audit_classifications(
    snap: ModelSnapshot,
    catalog: RequirementsCatalog,
    phase: BIMPhase,
) -> list[Finding]:
    findings: list[Finding] = []

    # Phases où la classification est attendue selon I3F (à partir d'AVP/PRO)
    if phase in (BIMPhase.APS,):
        return findings

    for ifc_class, elements in snap.elements_by_type.items():
        if ifc_class in NON_CLASSIFIED_IFC:
            continue
        for el in elements:
            classifs = el.get("classifications") or []
            uuid = el.get("uuid")
            nm = get_attribute(el, "Name") or el.get("name")
            if not classifs:
                findings.append(
                    Finding(
                        theme=Theme.CLASSIFICATION,
                        severity=Severity.MEDIUM,
                        error_type=ErrorType.CLASSIFICATION_MISSING,
                        element_uuid=uuid,
                        ifc_type=ifc_class,
                        name=nm,
                        expected="≥ 1 classification IFC (UniFormat / Omniclass / table 3F)",
                        actual=None,
                        ref_cch="Chap 6.2",
                        recommended_action=(
                            "Associer une classification métier au composant "
                            "(via IfcClassificationReference)."
                        ),
                    )
                )
                continue
            for c in classifs:
                code = c.get("notation") or c.get("name")
                source = c.get("source") or (c.get("system") or {}).get("name")
                if not code or not source:
                    findings.append(
                        Finding(
                            theme=Theme.CLASSIFICATION,
                            severity=Severity.LOW,
                            error_type=ErrorType.CLASSIFICATION_INVALID,
                            element_uuid=uuid,
                            ifc_type=ifc_class,
                            name=nm,
                            expected="Couple (Code/Notation, Source) renseigné",
                            actual={"code": code, "source": source},
                            ref_cch="Chap 6.2",
                            recommended_action=(
                                "Compléter la classification : préciser le code "
                                "ET la source (UniFormat, Omniclass, etc.)."
                            ),
                        )
                    )
    return findings
