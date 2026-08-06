"""Diagnostic des Psets MRN manquants — mesure, jamais mapping appliqué.

Sépare les exigences bloquées en deux populations que leur nombre confond :
celles dont le Pset attendu **n'a pas été saisi** dans la maquette, et celles
dont un Pset présent pourrait être l'équivalent.

Sur MN_BAT, 197 exigences sont bloquées : **21** ont leur propriété exacte
retrouvée sur une classe compatible, **176** n'ont aucun candidat. ``Pset_MRN``
attend 131 propriétés que la maquette ne porte pour l'essentiel nulle part —
aucun fichier de correspondance ne crée une donnée non saisie.

Un candidat est **local à une exigence** : il doit porter la propriété exacte
demandée, sur la classe visée ou une sous-classe acceptée. Un recouvrement de
groupe ne suffit pas — ``Pset_WindowCommon`` porte ``IsExternal``, l'une des 25
propriétés attendues sur les fenêtres ; en tirer un mapping global ferait passer
les 25 exigences en « évaluable » alors qu'une seule donnée est là.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from .coverage import matching_classes


def _normalize_property(name: str) -> str:
    """Comparaison de noms de propriete : casse et separateurs seulement."""
    return "".join(ch for ch in str(name or "").lower() if ch.isalnum())


__all__ = ["MappingCandidate", "PsetGap", "diagnose_pset_gap"]


@dataclass(frozen=True)
class MappingCandidate:
    """Proposition **non validée**, portant sur UNE exigence précise.

    Le score est local : un candidat n'existe que s'il porte **la propriété
    exacte** de l'exigence, sur une classe compatible. Un recouvrement de groupe
    ne suffit pas — ``Pset_WindowCommon`` contient ``IsExternal``, l'une des 25
    propriétés attendues sur les fenêtres ; en tirer un mapping
    ``Pset_MRN -> Pset_WindowCommon`` ferait passer les 25 exigences en
    « évaluable » alors qu'une seule donnée est réellement là.
    """

    candidate_source_pset: str
    required_property: str
    matched_property: str
    same_ifc_scope: bool
    confidence: float = 1.0
    requires_human_validation: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_source_pset": self.candidate_source_pset,
            "required_property": self.required_property,
            "matched_property": self.matched_property,
            "same_ifc_scope": self.same_ifc_scope,
            "confidence": self.confidence,
            "requires_human_validation": self.requires_human_validation,
        }


@dataclass(frozen=True)
class PsetGap:
    """Un Pset attendu, sur une classe donnée, et ce que la maquette en offre."""

    sheet: str
    ifc_object: str
    expected_pset: str
    expected_properties: list[str]
    requirements: int
    resolvable_by_mapping: bool
    #: Part des proprietes attendues retrouvees quelque part sur la classe.
    #: Diagnostic uniquement : ce taux ne debloque aucune exigence.
    group_overlap_rate: float = 0.0
    candidates: list[MappingCandidate] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sheet": self.sheet,
            "ifc_object": self.ifc_object,
            "expected_pset": self.expected_pset,
            "expected_properties": list(self.expected_properties),
            "requirements": self.requirements,
            "resolvable_by_mapping": self.resolvable_by_mapping,
            "group_overlap_rate": self.group_overlap_rate,
            "candidates": [c.to_dict() for c in self.candidates],
        }


def _properties_by_pset(elements, classes: set[str]) -> dict[str, set[str]]:
    """Propriétés portées par chaque Pset, restreint aux classes visées."""
    found: dict[str, set[str]] = defaultdict(set)
    for element in elements:
        if (element.get("type") or "") not in classes:
            continue
        for pset in element.get("property_sets") or []:
            name = pset.get("name")
            if not name:
                continue
            for prop in pset.get("properties") or []:
                label = (prop.get("definition") or {}).get("name") or prop.get("name")
                if label:
                    found[name].add(str(label))
    return found


def diagnose_pset_gap(blocked_requirements, snapshot) -> list[PsetGap]:
    """Décrit chaque Pset attendu et manquant, avec ses candidats éventuels.

    Args:
        blocked_requirements: exigences MRN dont le Pset n'a pas été retrouvé.
        snapshot: ``ModelSnapshot`` de la maquette analysée.

    Returns:
        Un :class:`PsetGap` par couple (feuille, classe, Pset attendu), trié par
        nombre d'exigences décroissant. ``resolvable_by_mapping`` est ``False``
        quand aucun Pset présent ne porte la moindre propriété attendue — le cas
        d'une donnée non saisie, qu'aucune correspondance ne répare.
    """
    elements = list(getattr(snapshot, "elements", None) or [])
    grouped: dict[tuple[str, str, str], list] = defaultdict(list)
    for requirement in blocked_requirements:
        key = (requirement.sheet, requirement.ifc_object, requirement.pset)
        grouped[key].append(requirement)

    gaps: list[PsetGap] = []
    for (sheet, ifc_object, expected_pset), rows in grouped.items():
        expected = sorted({r.property_name for r in rows if r.property_name})
        available = _properties_by_pset(elements, matching_classes(ifc_object))

        # Un candidat par EXIGENCE : il doit porter la propriete exacte
        # demandee, sur une classe compatible. Sans cette localite, un seul nom
        # partage suffirait a declarer mappable tout un groupe.
        required = {r.property_name for r in rows if r.property_name}
        candidates: list[MappingCandidate] = []
        seen: set[tuple[str, str]] = set()
        for source, properties in available.items():
            by_norm = {_normalize_property(p): p for p in properties}
            for wanted in sorted(required):
                match = by_norm.get(_normalize_property(wanted))
                if not match or (source, wanted) in seen:
                    continue
                seen.add((source, wanted))
                candidates.append(
                    MappingCandidate(
                        candidate_source_pset=source,
                        required_property=wanted,
                        matched_property=match,
                        same_ifc_scope=True,
                    )
                )

        found = {c.required_property for c in candidates}
        overlap = round(len(found) / len(expected), 3) if expected else 0.0

        candidates.sort(key=lambda c: (c.required_property, c.candidate_source_pset))
        gaps.append(
            PsetGap(
                sheet=sheet,
                ifc_object=ifc_object,
                expected_pset=expected_pset,
                expected_properties=expected,
                requirements=len(rows),
                resolvable_by_mapping=bool(candidates),
                group_overlap_rate=overlap,
                candidates=candidates,
            )
        )

    gaps.sort(key=lambda g: (-g.requirements, g.expected_pset))
    return gaps
