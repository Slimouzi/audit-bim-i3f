"""Audit des classifications IFC sur les composants.

Les classifications I3F (UniFormat, Omniclass, ou table interne 3F) doivent
être renseignées sur chaque composant physique pour permettre l'exploitation
(GMAO, DOE). On vérifie :
- la *présence* d'au moins une classification,
- la *cohérence* du couple (Code, Source) : si une classification est attachée,
  elle doit avoir une notation/code non vide.
"""
from __future__ import annotations

import re

from ...classifier import accepted_codes_for, normalize_uniformat_level3, suggest
from ...extraction.model_data import ModelSnapshot
from ...extraction.normalizer import get_attribute
from ...requirements.models import BIMPhase, RequirementsCatalog
from ..findings import ErrorType, Finding, Severity, Theme

# Seuil de confiance min pour qu'une suggestion soit utilisée comme argument
# de cohérence (en dessous, on ne signale pas — l'heuristique est trop incertaine).
SUGGESTION_CONFIDENCE_THRESHOLD = 0.5

# Un code UniFormat II : lettre A-E + au moins 4 chiffres (E2020, B2010100…).
# Sert à auto-détecter qu'une classification *sans source explicite* est
# probablement UniFormat — courant dans les exports Revit.
_UNIFORMAT_CODE_RE = re.compile(r"^[A-E]\d{4,}$")


def _looks_uniformat(code: str, source: str | None) -> bool:
    """Vrai si on doit traiter ``code`` comme du UniFormat (juger cohérence)."""
    if source and "uniformat" in str(source).lower():
        return True
    cleaned = "".join(ch for ch in str(code or "").upper() if ch.isalnum())
    return bool(_UNIFORMAT_CODE_RE.match(cleaned))

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
            # Complétude par classification + cohérence métier niveau 3
            existing_level3: set[str] = set()
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
                    continue
                # Cohérence niveau 3 : on traite le code comme UniFormat si
                # la source l'indique OU si le code en a la forme (lettre A-E
                # + chiffres) — courant quand l'export Revit oublie la source.
                if _looks_uniformat(code, source):
                    existing_level3.add(normalize_uniformat_level3(code))

            # Cohérence : la classification niveau 3 existante doit appartenir
            # à la *famille* de codes plausibles pour la classe IFC (top
            # suggéré + alternatives connues — ex: IfcFurnishingElement accepte
            # E2010 Fixed et E2020 Movable). On ne signale que si la suggestion
            # est suffisamment confiante.
            if existing_level3:
                sugs = suggest(el)
                if sugs and sugs[0].confidence >= SUGGESTION_CONFIDENCE_THRESHOLD:
                    top = sugs[0]
                    accepted = accepted_codes_for(ifc_class, top.classification.code)
                    # Si AUCUN code existant ne fait partie de la famille → erreur
                    if accepted and not (existing_level3 & accepted):
                        findings.append(
                            Finding(
                                theme=Theme.CLASSIFICATION,
                                severity=Severity.MEDIUM,
                                error_type=ErrorType.CLASSIFICATION_INVALID,
                                element_uuid=uuid,
                                ifc_type=ifc_class,
                                name=nm,
                                expected=(
                                    f"Classification niveau 3 cohérente avec "
                                    f"{ifc_class} — codes acceptés : "
                                    f"{sorted(accepted)} "
                                    f"(suggestion top : {top.classification.code} "
                                    f"— {top.classification.label}, conf. "
                                    f"{top.confidence:.2f})"
                                ),
                                actual=sorted(existing_level3),
                                ref_cch="Chap 6.2",
                                recommended_action=(
                                    f"Vérifier que la classification métier "
                                    f"appartient bien à {sorted(accepted)}. Si "
                                    "le modèle utilise un code raffiné "
                                    "(niveau 4+), son préfixe niveau 3 doit "
                                    "rester dans cette famille."
                                ),
                            )
                        )
    return findings
