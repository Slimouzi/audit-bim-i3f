"""Rapprochement DOE ↔ IFC — stratégies en cascade.

Pour chaque DoeRecord, on essaie successivement :

1. **GUID** (uuid_hint exact match avec un UUID IFC du modèle) → confiance 1.0
2. **Tag/Mark** (tag_hint match strict avec un Tag IFC ou Pset_*Common.Tag/Mark)
   → confiance 0.9
3. **Nom fuzzy** (rapidfuzz score ≥ seuil sur le Name) → confiance = score
4. **Localisation + type** (étage + zone + type IFC) → confiance 0.5–0.7

La première stratégie qui *retient un candidat unique* gagne. En cas
d'ambiguïté (plusieurs candidats à confiance proche), on remplit la liste
``candidates`` du Match pour que l'auditeur tranche.
"""
from __future__ import annotations

from rapidfuzz import fuzz, process

from ..extraction.model_data import ModelSnapshot
from ..extraction.normalizer import get_attribute
from .models import DoeRecord, Match

# Seuils
TAG_EXACT_CONFIDENCE = 0.90
GUID_CONFIDENCE = 1.0
NAME_FUZZY_MIN_SCORE = 75  # /100
LOCALISATION_CONFIDENCE = 0.55


def _element_tag(el: dict) -> str | None:
    """Récupère le Tag/Mark d'un élément (cf. règle uniqueness)."""
    for pset in el.get("property_sets") or []:
        pn = (pset.get("name") or "")
        if "Common" not in pn:
            continue
        for prop in pset.get("properties") or []:
            nm = ((prop.get("definition") or {}).get("name") or "").lower()
            if nm in ("tag", "mark"):
                v = prop.get("value")
                if v not in (None, ""):
                    return str(v).strip()
    tag = get_attribute(el, "Tag")
    return str(tag).strip() if tag not in (None, "") else None


def match_doe_records(
    records: list[DoeRecord],
    snap: ModelSnapshot,
    *,
    name_min_score: int = NAME_FUZZY_MIN_SCORE,
) -> list[Match]:
    """Rapproche chaque DoeRecord à un élément du snapshot."""
    # Pré-indexation
    elements = list(snap.element_by_uuid.values())
    by_uuid = snap.element_by_uuid
    by_tag: dict[str, list[dict]] = {}
    name_index: list[tuple[str, dict]] = []  # (name_lower, element)
    for el in elements:
        tag = _element_tag(el)
        if tag:
            by_tag.setdefault(tag.lower(), []).append(el)
        nm = (
            get_attribute(el, "Name")
            or el.get("name")
            or get_attribute(el, "LongName")
            or el.get("longname")
            or ""
        )
        if nm:
            name_index.append((str(nm), el))

    matches: list[Match] = []
    for rec in records:
        # 1. GUID exact
        if rec.uuid_hint and rec.uuid_hint in by_uuid:
            el = by_uuid[rec.uuid_hint]
            matches.append(
                Match(
                    record=rec,
                    ifc_uuid=rec.uuid_hint,
                    ifc_type=el.get("type"),
                    ifc_name=el.get("name"),
                    confidence=GUID_CONFIDENCE,
                    strategy="guid",
                )
            )
            continue

        # 2. Tag / Mark
        if rec.tag_hint:
            cands = by_tag.get(str(rec.tag_hint).strip().lower(), [])
            if len(cands) == 1:
                el = cands[0]
                matches.append(
                    Match(
                        record=rec,
                        ifc_uuid=el.get("uuid"),
                        ifc_type=el.get("type"),
                        ifc_name=el.get("name"),
                        confidence=TAG_EXACT_CONFIDENCE,
                        strategy="tag",
                    )
                )
                continue
            if len(cands) > 1:
                matches.append(
                    Match(
                        record=rec,
                        confidence=0.0,
                        candidates=[
                            {
                                "uuid": e.get("uuid"),
                                "type": e.get("type"),
                                "name": e.get("name"),
                                "score": TAG_EXACT_CONFIDENCE,
                            }
                            for e in cands[:5]
                        ],
                        reason=(
                            f"Tag « {rec.tag_hint} » correspond à "
                            f"{len(cands)} éléments — ambiguïté."
                        ),
                    )
                )
                continue

        # 3. Nom fuzzy
        if rec.name_hint and name_index:
            choices = [n for n, _ in name_index]
            best = process.extract(
                rec.name_hint,
                choices,
                scorer=fuzz.token_set_ratio,
                limit=5,
            )
            # best = [(matched_name, score, index), ...]
            if best and best[0][1] >= name_min_score:
                # On filtre éventuellement par type IFC pour réduire les faux positifs
                candidates = [
                    (name_index[i][1], score) for _name, score, i in best
                ]
                if rec.type_hint:
                    candidates = _filter_by_type(candidates, rec.type_hint) or candidates
                el, score = candidates[0]
                matches.append(
                    Match(
                        record=rec,
                        ifc_uuid=el.get("uuid"),
                        ifc_type=el.get("type"),
                        ifc_name=el.get("name"),
                        confidence=score / 100.0,
                        strategy="name",
                        candidates=[
                            {
                                "uuid": e.get("uuid"),
                                "type": e.get("type"),
                                "name": e.get("name"),
                                "score": sc / 100.0,
                            }
                            for e, sc in candidates[1:5]
                        ],
                    )
                )
                continue

        # 4. Pas de match
        matches.append(
            Match(
                record=rec,
                reason=(
                    "Aucun indice exploitable : "
                    f"uuid={rec.uuid_hint!r}, tag={rec.tag_hint!r}, "
                    f"name={rec.name_hint!r}."
                ),
            )
        )
    return matches


def _filter_by_type(
    candidates: list[tuple[dict, int]], type_hint: str
) -> list[tuple[dict, int]]:
    """Filtre les candidats dont la classe IFC contient le type_hint."""
    th = type_hint.lower()
    return [
        (el, sc)
        for el, sc in candidates
        if th in (el.get("type") or "").lower()
    ]
