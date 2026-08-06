"""Couverture du référentiel MRN sur une maquette — évaluabilité, pas conformité.

Ce module répond à une seule question : **combien des 1 013 exigences MRN
peut-on réellement évaluer sur cette maquette, et pourquoi pas les autres ?**

Il ne produit aucun statut de conformité, et c'est délibéré. La mesure faite sur
MN_BAT montre pourquoi : 532 exigences sur 532 de ``CVC-PLB-SSI-ELEC`` visent
des classes IFC absentes d'une maquette architecturale. Un moteur qui trancherait
« non conforme » par défaut produirait **plus de la moitié du référentiel en faux
constats** — un livrable crédible, chiffré, et faux.

La normalisation douce des noms de Pset est appliquée, et ne rattrape rien : zéro
correspondance sur les quatre feuilles. L'écart de nommage n'est donc ni de
casse, ni d'accent, ni de séparateur, mais de vocabulaire. Aucun mapping métier
n'est inventé ici — il demande une validation humaine, pas une heuristique.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

__all__ = ["COVERAGE_STATUSES", "MRNCoverage", "assess_mrn_coverage", "normalize_pset"]

#: Les seuls statuts que ce lot produit. Aucun n'est un jugement de conformité :
#: ils disent si l'exigence est **évaluable**, et sinon ce qui l'en empêche.
COVERAGE_STATUSES = (
    "evaluable_pset_exact",
    "evaluable_without_pset",
    "hors_perimetre_modele",
    "non_evaluable_classe_absente",
    "non_evaluable_mapping_pset",
    "non_evaluable_donnee_absente",
)


def normalize_pset(name: str) -> str:
    """Normalisation **douce** : casse, accents, séparateurs, préfixe ``Pset_``.

    Volontairement mécanique. Rapprocher ``Pset_CoveringCommon`` d'un Pset
    métier au nom différent relève d'une décision humaine, pas d'une règle de
    chaîne — et une heuristique généreuse produirait des correspondances fausses
    qu'aucun relecteur ne pourrait distinguer des vraies.
    """
    text = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode()
    text = re.sub(r"^pset[_\- ]*", "", text.lower())
    return re.sub(r"[\s_\-]+", "", text)


@dataclass(frozen=True)
class RequirementCoverage:
    """Verdict d'évaluabilité d'une exigence, avec sa cause."""

    sheet: str
    row: int
    property_name: str
    ifc_object: str
    pset: str
    status: str
    pset_match_kind: str  # exact | normalized | missing | not_declared
    carrier_declared: bool


@dataclass(frozen=True)
class MRNCoverage:
    """Synthèse de couverture. **Pas** une grille de conformité."""

    model_name: str
    requirements: list[RequirementCoverage] = field(default_factory=list)
    model_classes: set[str] = field(default_factory=set)
    model_psets: set[str] = field(default_factory=set)

    @property
    def evaluable(self) -> list[RequirementCoverage]:
        return [r for r in self.requirements if r.status.startswith("evaluable")]

    def _per(self, key) -> dict[str, int]:
        return dict(Counter(key(r) for r in self.requirements))

    def summary(self) -> dict[str, Any]:
        total = len(self.requirements)
        evaluable = len(self.evaluable)
        per_sheet: dict[str, Any] = {}
        for sheet in sorted({r.sheet for r in self.requirements}):
            rows = [r for r in self.requirements if r.sheet == sheet]
            per_sheet[sheet] = {
                "requirements": len(rows),
                "evaluable": sum(1 for r in rows if r.status.startswith("evaluable")),
                "by_status": dict(Counter(r.status for r in rows)),
                "pset_exact": sum(1 for r in rows if r.pset_match_kind == "exact"),
                "pset_normalized": sum(1 for r in rows if r.pset_match_kind == "normalized"),
                "pset_missing": sum(1 for r in rows if r.pset_match_kind == "missing"),
                "pset_not_declared": sum(1 for r in rows if r.pset_match_kind == "not_declared"),
                "carrier_declared": sum(1 for r in rows if r.carrier_declared),
                "absent_classes": sum(
                    1 for r in rows if r.status == "non_evaluable_classe_absente"
                ),
            }
        return {
            "model_name": self.model_name,
            "requirements_total": total,
            "requirements_evaluable": evaluable,
            "evaluability_rate": round(evaluable / total, 4) if total else 0.0,
            "by_status": self._per(lambda r: r.status),
            "by_pset_match": self._per(lambda r: r.pset_match_kind),
            "per_sheet": per_sheet,
            "model_classes": len(self.model_classes),
            "model_psets": len(self.model_psets),
            "verdict": self.verdict(),
        }

    def verdict(self) -> str:
        """Phrase que le lecteur doit retenir, pas un score à interpréter."""
        total = len(self.requirements) or 1
        rate = len(self.evaluable) / total
        if rate < 0.25:
            return (
                "Ce référentiel MRN n'est pas suffisamment évaluable sur cette maquette "
                "seule. Le livrable exploitable est une synthèse de couverture, pas une "
                "grille de conformité."
            )
        return (
            f"{len(self.evaluable)} exigences sur {total} sont évaluables sur cette "
            f"maquette. Une grille de conformité reste partielle."
        )


def assess_mrn_coverage(requirements, snapshot, *, model_name: str = "") -> MRNCoverage:
    """Confronte les exigences MRN à un snapshot, sans juger la conformité.

    Args:
        requirements: exigences issues de ``parse_mrn_attribute_table``.
        snapshot: ``ModelSnapshot`` de la maquette ciblée.
        model_name: nom du modèle, repris tel quel dans la synthèse.
    """
    elements = list(getattr(snapshot, "elements", None) or [])
    model_classes = {(el.get("type") or "") for el in elements if el.get("type")}
    model_psets = {
        pset.get("name")
        for el in elements
        for pset in (el.get("property_sets") or [])
        if pset.get("name")
    }
    normalized_psets = {normalize_pset(name) for name in model_psets}

    assessed: list[RequirementCoverage] = []
    for requirement in requirements:
        pset = requirement.pset
        if not pset:
            match = "not_declared"
        elif pset in model_psets:
            match = "exact"
        elif normalize_pset(pset) in normalized_psets:
            match = "normalized"
        else:
            match = "missing"

        carrier_declared = bool(requirement.carrier_models)

        if requirement.ifc_object and requirement.ifc_object not in model_classes:
            # Une classe absente n'est jamais une non-conformité par défaut : rien
            # ne dit que cette maquette devait la porter. Seule une colonne
            # porteuse permet de trancher, et les feuilles techniques n'en ont pas.
            status = "hors_perimetre_modele" if carrier_declared else "non_evaluable_classe_absente"
        elif match == "exact":
            status = "evaluable_pset_exact"
        elif match == "not_declared":
            # Propriété à chercher en trois niveaux (attribut racine, quantités,
            # tous Psets) — la recherche relève du moteur de contrôle, pas de la
            # couverture. Ici on constate seulement qu'elle est possible.
            status = "evaluable_without_pset"
        elif match == "normalized":
            status = "evaluable_pset_exact"
        else:
            status = "non_evaluable_mapping_pset"

        assessed.append(
            RequirementCoverage(
                sheet=requirement.sheet,
                row=requirement.row,
                property_name=requirement.property_name,
                ifc_object=requirement.ifc_object,
                pset=pset,
                status=status,
                pset_match_kind=match,
                carrier_declared=carrier_declared,
            )
        )

    return MRNCoverage(
        model_name=model_name,
        requirements=assessed,
        model_classes=model_classes,
        model_psets=model_psets,
    )
