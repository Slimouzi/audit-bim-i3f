"""Rapprochement DOE ↔ IFC — 4 stratégies en cascade.

Pour chaque DoeRecord, on essaie successivement :

1. **GUID** — uuid_hint exact match avec un UUID IFC du modèle.
   Confiance 1.0.
2. **Tag/Mark** — tag_hint match strict avec un Tag IFC ou
   Pset_*Common.Tag/Mark. Confiance 0.9.
3. **Nom fuzzy** — rapidfuzz score ≥ seuil sur le Name.
   Confiance = score / 100.
4. **Localisation** — étage + zone + type IFC. Match retenu seulement
   si **un seul** élément correspond. Confiance 0.55.

La première stratégie qui retient un candidat unique gagne. En cas
d'ambiguïté (plusieurs candidats), on remplit la liste ``candidates``
du Match pour que l'auditeur tranche.
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
        pn = pset.get("name") or ""
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


def build_localization_index(snap: ModelSnapshot) -> dict[str, dict[str, str | None]]:
    """Construit l'index ``element_uuid → {storey_name, zone_name}``.

    Parcourt l'arborescence spatiale ``snap.structure_tree`` en
    profondeur pour propager le contexte (étage et zone courants) à
    chaque élément descendant. Si l'arbre est vide ou inutilisable,
    l'index est construit à partir des relations directes
    (``snap.zones`` ↔ ``snap.spaces`` ↔ ``snap.elements`` quand
    elles sont exposées).

    Args:
        snap: Photo du modèle IFC.

    Returns:
        Dict ``{uuid: {"storey": <nom étage|None>, "zone": <nom zone|None>}}``.
        Les éléments hors arborescence (orphelins, IfcGrid, etc.)
        ne figurent pas dans l'index.
    """
    index: dict[str, dict[str, str | None]] = {}

    def _walk(node: dict, current_storey: str | None, current_zone: str | None):
        if not isinstance(node, dict):
            return
        node_type = node.get("type") or ""
        node_name = node.get("name") or None
        if node_type == "IfcBuildingStorey":
            current_storey = node_name or current_storey
        elif node_type == "IfcZone":
            current_zone = node_name or current_zone
        node_uuid = node.get("uuid")
        if node_uuid:
            existing = index.get(node_uuid, {})
            index[node_uuid] = {
                "storey": existing.get("storey") or current_storey,
                "zone": existing.get("zone") or current_zone,
            }
        for child in node.get("children") or []:
            _walk(child, current_storey, current_zone)

    for root in snap.structure_tree or []:
        _walk(root, None, None)
    return index


def _normalize_for_compare(s: str | None) -> str:
    """Normalisation simple pour comparaison de noms (étage, zone, type)."""
    if not s:
        return ""
    return str(s).strip().casefold()


def _filter_by_localisation(
    elements: list[dict],
    rec: DoeRecord,
    loc_index: dict[str, dict[str, str | None]],
) -> list[dict]:
    """Filtre les éléments dont localisation matche les indices du record.

    Critères combinés (ET) — un critère vide côté record est ignoré :

    - ``rec.storey_hint`` vs ``loc_index[uuid]["storey"]``
    - ``rec.zone_hint`` vs ``loc_index[uuid]["zone"]``
    - ``rec.type_hint`` vs ``element["type"]`` (substring case-insensitive)

    Comparaisons : casefold + strip côté noms ; substring côté type.

    Args:
        elements: Liste candidate à filtrer.
        rec: DoeRecord avec ses hints de localisation.
        loc_index: Index produit par :func:`build_localization_index`.

    Returns:
        Sous-ensemble d'éléments respectant tous les critères non vides.
    """
    storey_target = _normalize_for_compare(rec.storey_hint)
    zone_target = _normalize_for_compare(rec.zone_hint)
    type_target = _normalize_for_compare(rec.type_hint)

    out: list[dict] = []
    for el in elements:
        uuid = el.get("uuid") or ""
        loc = loc_index.get(uuid, {})
        if storey_target and _normalize_for_compare(loc.get("storey")) != storey_target:
            continue
        if zone_target and _normalize_for_compare(loc.get("zone")) != zone_target:
            continue
        if type_target and type_target not in _normalize_for_compare(el.get("type")):
            continue
        out.append(el)
    return out


def match_doe_records(
    records: list[DoeRecord],
    snap: ModelSnapshot,
    *,
    name_min_score: int = NAME_FUZZY_MIN_SCORE,
) -> list[Match]:
    """Rapproche chaque DoeRecord à un élément IFC du snapshot.

    Stratégies tentées dans l'ordre — la première qui réussit gagne :

    1. **GUID exact** (``uuid_hint`` ∈ ``element_by_uuid``) — confiance 1.0.
    2. **Tag/Mark exact** sur Pset_*Common ou attribut natif — confiance
       0.9. En cas d'ambiguïté (plusieurs éléments avec le même tag), le
       match est *refusé* et les candidats listés.
    3. **Nom fuzzy** (rapidfuzz ``token_set_ratio``) — confiance = score /
       100. Filtré par type_hint si renseigné.
    4. **Localisation** (étage + zone + type, combinés en ET) — confiance
       0.55. Match retenu seulement si un seul élément correspond.

    Args:
        records: DoeRecord à rapprocher (issus des extracteurs).
        snap: ModelSnapshot du modèle IFC.
        name_min_score: Seuil rapidfuzz 0–100 sous lequel on rejette un
            match par nom. Défaut 75. Monter à 85+ pour réduire les faux
            positifs sur des modèles bruyants.

    Returns:
        Liste de Match, même longueur et même ordre que ``records``. Un
        Match peut être ``is_matched() == False`` (non match ou ambiguïté).
    """
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
    loc_index = build_localization_index(snap)

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
            if best and best[0][1] >= name_min_score:
                candidates = [(name_index[i][1], score) for _name, score, i in best]
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

        # 4. Localisation (étage + zone + type)
        if rec.storey_hint or rec.zone_hint or rec.type_hint:
            cands = _filter_by_localisation(elements, rec, loc_index)
            if len(cands) == 1:
                el = cands[0]
                matches.append(
                    Match(
                        record=rec,
                        ifc_uuid=el.get("uuid"),
                        ifc_type=el.get("type"),
                        ifc_name=el.get("name"),
                        confidence=LOCALISATION_CONFIDENCE,
                        strategy="localisation",
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
                                "score": LOCALISATION_CONFIDENCE,
                            }
                            for e in cands[:5]
                        ],
                        reason=(
                            f"Localisation (étage={rec.storey_hint!r}, "
                            f"zone={rec.zone_hint!r}, type={rec.type_hint!r}) "
                            f"correspond à {len(cands)} éléments — ambiguïté."
                        ),
                    )
                )
                continue

        # Pas de match
        matches.append(
            Match(
                record=rec,
                reason=(
                    "Aucun indice exploitable : "
                    f"uuid={rec.uuid_hint!r}, tag={rec.tag_hint!r}, "
                    f"name={rec.name_hint!r}, "
                    f"storey={rec.storey_hint!r}, zone={rec.zone_hint!r}, "
                    f"type={rec.type_hint!r}."
                ),
            )
        )
    return matches


def _filter_by_type(candidates: list[tuple[dict, int]], type_hint: str) -> list[tuple[dict, int]]:
    """Filtre les candidats dont la classe IFC contient le type_hint."""
    th = type_hint.lower()
    return [(el, sc) for el, sc in candidates if th in (el.get("type") or "").lower()]
