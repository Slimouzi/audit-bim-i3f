"""Audit de cohérence sur les listes fermées (rapprochement maquette ↔ CCH).

L'audit *naming* couvre déjà chaque élément un à un. Ici on traite le cas
inverse : rapprocher la *couverture* du modèle vs le référentiel.

Exemples remontés :
- Des étages présents dans la maquette ne figurent pas dans la liste du CCH
  (déjà couvert par naming) mais aussi à l'inverse, des étages obligatoires
  du CCH sont absents → moins fréquent, donc INFO uniquement.
- Une zone du référentiel I3F est totalement absente (info pour le MOA).
"""

from __future__ import annotations

from ...extraction.model_data import ModelSnapshot
from ...extraction.normalizer import get_attribute
from ...requirements.models import BIMPhase, RequirementsCatalog
from ..findings import ErrorType, Finding, Severity, Theme


def audit_lists(
    snap: ModelSnapshot,
    catalog: RequirementsCatalog,
    phase: BIMPhase,
) -> list[Finding]:
    findings: list[Finding] = []

    # Présence / absence des grandes typologies de zones I3F
    # (utile pour DOE/GESTION pour s'assurer que les Parties Communes sont modélisées)
    if phase in (BIMPhase.DOE, BIMPhase.GESTION):
        zone_types_in_model = {
            (get_attribute(z, "ObjectType") or z.get("object_type") or "").strip()
            for z in snap.of_class("IfcZone")
        }
        zone_types_required_pc = {
            z.type_label for z in catalog.zone_specs if z.localisation == "PC" and z.type_label
        }
        missing_pc = zone_types_required_pc - zone_types_in_model
        for z in sorted(missing_pc):
            findings.append(
                Finding(
                    theme=Theme.NAMING_ZONE,
                    severity=Severity.INFO,
                    error_type=ErrorType.NAMING_NOT_IN_LIST,
                    ifc_type="IfcZone",
                    expected=f"Présence d'une zone '{z}' (Partie Commune)",
                    actual="absent",
                    ref_cch="Chap 6.3.2.2",
                    recommended_action=(
                        f"Vérifier si une zone '{z}' doit être modélisée "
                        "(partie commune attendue par 3F)."
                    ),
                )
            )

    return findings
