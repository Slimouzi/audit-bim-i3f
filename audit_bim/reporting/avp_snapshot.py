"""Extraction AVP **source-first, snapshot en repli**.

Quand les fichiers sources I3F (Solibri/ArchiCAD) sont absents, on génère
néanmoins les exports SHAB, Zones/Espaces, Enveloppe et Menuiseries à partir
du ``ModelSnapshot`` de l'``AuditResult`` — pour ne jamais livrer une annexe
client qui ne contient que le bandeau.

Principes :

- **Source-first** : ce module ne fabrique un export que si la source I3F
  correspondante est absente/vide (arbitrage fait par l'orchestrateur).
- **Jamais inventer** : une surface introuvable reste ``None`` (rendue
  ``NOT_AVAILABLE``) ; la **source** de chaque valeur (BaseQuantities vs
  « Superficie calculée ») est tracée dans une colonne dédiée.
- **Tolérance** casse / accents / espaces sur les layers et les noms de
  propriétés (normalisation ``_norm``).
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from typing import Any

from ..extraction.model_data import ModelSnapshot
from .avp_sources import (
    AvpSources,
    EnveloppeSource,
    MenuiseriesSource,
    MultiSheetSource,
    SheetGrid,
    SheetTable,
)
from .word_report import NOT_AVAILABLE

# ── Sélection de l'enveloppe ────────────────────────────────────────────────
#
# Murs d'enveloppe : sélection **par layer** (critère autoritaire I3F).
# Classes retenues : IfcWall + IfcWallStandardCase.
#
# Décision explicite : **IfcCurtainWall EXCLU**. Les murs-rideaux sont des
# façades vitrées comptées en *menuiseries* (surface des ouvertures), pas en
# surface de murs opaques d'enveloppe ; par ailleurs le layer cible
# « MURS - Extérieurs périphériques.Exnd » ne les porte pas. Pour l'inclure
# un jour, ajouter la classe ici et adapter la synthèse façades/menuiseries.
_ENVELOPE_WALL_CLASSES = ("IfcWall", "IfcWallStandardCase")
_ENVELOPE_LAYER = "MURS - Extérieurs périphériques.Exnd"

# Ordre de résolution des surfaces (BaseQuantities), puis repli propriété.
_WALL_BQ_ORDER = ("NetSideArea", "GrossSideArea", "NetArea", "GrossArea")
_SPACE_BQ_ORDER = ("NetFloorArea", "GrossFloorArea", "NetArea", "GrossArea")
_WINDOW_BQ_AREA = ("Area", "NetArea", "GrossArea")
_SUPERFICIE_PROP = "Superficie calculée"


def _norm(s: Any) -> str:
    """Normalise pour comparaison tolérante (accents / casse / espaces)."""
    if s is None:
        return ""
    txt = unicodedata.normalize("NFKD", str(s))
    txt = "".join(c for c in txt if not unicodedata.combining(c))
    return " ".join(txt.lower().split())


_ENVELOPE_LAYER_NORM = _norm(_ENVELOPE_LAYER)


# ── Accesseurs bas niveau (tolérants) ───────────────────────────────────────


def _attr(el: dict, name: str) -> str:
    """Attribut IFC natif (Name, LongName…) sous forme de chaîne ('' si absent)."""
    key = name.lower()
    v = el.get(key) or el.get(name)
    if v in (None, ""):
        for prop in (el.get("attributes") or {}).get("properties") or []:
            nm = (prop.get("definition") or {}).get("name") or ""
            if nm.lower() == key:
                v = prop.get("value")
                break
    return "" if v in (None, "") else str(v)


def _label(el: dict) -> str:
    """Libellé exporté : LongName, sinon Name (fallback si LongName vide)."""
    ln = _attr(el, "LongName")
    if ln.strip():
        return ln.strip()
    return _attr(el, "Name").strip()


def _ifc_type(el: dict) -> str:
    ot = _attr(el, "ObjectType")
    if ot.strip():
        return ot.strip()
    pt = _attr(el, "PredefinedType")
    if pt.strip():
        return pt.strip()
    return el.get("type") or ""


def _storey(el: dict) -> str:
    for key in ("storey", "building_storey", "storey_name", "floor", "parent"):
        v = el.get(key)
        if isinstance(v, dict):
            nm = v.get("name")
            if nm:
                return str(nm)
        elif isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _material(el: dict) -> str:
    for m in el.get("material_list") or []:
        nm = (m.get("material") or {}).get("name")
        if nm:
            return str(nm)
    return ""


def _is_bq_pset(pset: dict) -> bool:
    return bool(re.match(r"^(basequantities|qto_|quantit)", _norm(pset.get("name"))))


def _base_quantity_ordered(el: dict, names: tuple[str, ...]) -> float | None:
    """Première BaseQuantity trouvée dans l'ordre ``names`` (accent-insensible)."""
    for name in names:
        target = _norm(name)
        for pset in el.get("property_sets") or []:
            if not _is_bq_pset(pset):
                continue
            for prop in pset.get("properties") or []:
                if _norm((prop.get("definition") or {}).get("name")) == target:
                    val = prop.get("value")
                    if isinstance(val, (int, float)):
                        return float(val)
    return None


def _prop_any_pset(el: dict, prop_name: str) -> float | None:
    """Valeur numérique d'une propriété cherchée dans **tous** les Psets
    (accent-insensible) — sert au repli « Superficie calculée »."""
    target = _norm(prop_name)
    for pset in el.get("property_sets") or []:
        for prop in pset.get("properties") or []:
            if _norm((prop.get("definition") or {}).get("name")) == target:
                val = prop.get("value")
                if isinstance(val, (int, float)):
                    return float(val)
    return None


def _surface_with_source(el: dict, bq_order: tuple[str, ...]) -> tuple[float | None, str | None]:
    """Surface + traçabilité : BaseQuantities (ordre) → « Superficie calculée »."""
    v = _base_quantity_ordered(el, bq_order)
    if v is not None:
        return v, "BaseQuantities"
    v = _prop_any_pset(el, _SUPERFICIE_PROP)
    if v is not None:
        return v, "Superficie calculée"
    return None, None


def _rich(snap: ModelSnapshot, item: dict) -> dict:
    """Version la plus riche d'un élément (index par UUID = psets/layers)."""
    u = item.get("uuid")
    if u and u in snap.element_by_uuid:
        return snap.element_by_uuid[u]
    return item


def _has_envelope_layer(el: dict) -> bool:
    for layer in el.get("layers") or []:
        if isinstance(layer, dict) and _norm(layer.get("name")) == _ENVELOPE_LAYER_NORM:
            return True
    return False


def _envelope_walls(snap: ModelSnapshot) -> list[dict]:
    walls: list[dict] = []
    for cls in _ENVELOPE_WALL_CLASSES:
        walls.extend(snap.of_class(cls))
    return [w for w in walls if _has_envelope_layer(w)]


def count_envelope_walls(snap: ModelSnapshot | None) -> int:
    """Nombre de murs d'enveloppe exploitables (pour la QA gate)."""
    return len(_envelope_walls(snap)) if snap is not None else 0


# ── Relations zone → espaces, étage → espaces ───────────────────────────────


def _child_space_uuids(container: dict) -> list[str]:
    """UUID des espaces listés par un conteneur (zone ou étage)."""
    out: list[str] = []
    for key in ("spaces", "space_uuids", "elements", "related_spaces", "space_ids", "children"):
        v = container.get(key)
        if isinstance(v, list):
            for item in v:
                if isinstance(item, str):
                    out.append(item)
                elif isinstance(item, dict):
                    u = item.get("uuid") or item.get("id")
                    if u:
                        out.append(str(u))
    return out


def _zone_member_uuids(zone: dict) -> list[str]:
    return _child_space_uuids(zone)


def _space_zone_uuid(space: dict) -> str | None:
    for key in ("zone", "zone_uuid", "zone_id"):
        v = space.get(key)
        if isinstance(v, dict):
            u = v.get("uuid") or v.get("id")
            if u:
                return str(u)
        elif isinstance(v, str) and v.strip():
            return v.strip()
    return None


def _storey_label(storey: dict) -> str:
    return _label(storey) or _attr(storey, "Name")


def _build_space_zone_map(snap: ModelSnapshot) -> dict[str, list[str]]:
    """``space_uuid → [noms de zones]`` (un espace peut être dans plusieurs
    zones ; ex. duplex rattaché à des zones d'étage distinctes)."""
    zmap: dict[str, list[str]] = defaultdict(list)
    spaces = snap.spaces or []
    for z in snap.zones or []:
        zname = _label(_rich(snap, z)) or _attr(z, "Name")
        if not zname:
            continue
        members = _zone_member_uuids(z)
        if not members:
            members = [sp.get("uuid") for sp in spaces if _space_zone_uuid(sp) == z.get("uuid")]
        for u in members:
            if u and zname not in zmap[u]:
                zmap[u].append(zname)
    return zmap


def _build_space_storey_map(snap: ModelSnapshot) -> dict[str, list[str]]:
    """``space_uuid → [noms d'étages]``.

    Multi-valué : un même espace peut être rattaché à plusieurs étages
    (ex. **duplex** dont la zone traverse deux niveaux), et un étage peut
    lister ses espaces. On agrège toutes les sources sans jamais inventer.
    """
    smap: dict[str, list[str]] = defaultdict(list)
    storeys = snap.storeys or []
    by_uuid = {st.get("uuid"): st for st in storeys}

    def _add(u: str | None, name: str | None) -> None:
        if u and name and name not in smap[u]:
            smap[u].append(name)

    # 1. étage → ses espaces
    for st in storeys:
        sname = _storey_label(st)
        for u in _child_space_uuids(st):
            _add(u, sname)
    # 2. espace → son/ses étage(s) (attribut nom direct + référence UUID)
    for sp in snap.spaces or []:
        u = sp.get("uuid")
        _add(u, _storey(sp) or None)
        for key in ("storey", "building_storey", "storey_uuid", "storey_id", "parent", "storeys"):
            v = sp.get(key)
            refs = v if isinstance(v, list) else [v]
            for ref in refs:
                ru = None
                if isinstance(ref, str):
                    ru = ref
                elif isinstance(ref, dict):
                    ru = ref.get("uuid") or ref.get("id")
                if ru and ru in by_uuid:
                    _add(u, _storey_label(by_uuid[ru]))
    return smap


# ── Builders (snapshot → dataclasses source AVP) ────────────────────────────

# « Zone » = zone(s) contenant l'espace ; « Étage » = étage(s) — les deux
# multi-valués (séparés par « / ») pour couvrir les duplex (zone traversant
# plusieurs niveaux) et un espace rattaché à plusieurs zones d'étage.
_SPACE_HEADERS = [
    "Composant",
    "Libellé",
    "Zone",
    "Étage",
    "Type",
    "Surface (m²)",
    "Source surface",
]

_MULTI_SEP = " / "


def _spaces_grid(snap: ModelSnapshot, title: str) -> tuple[SheetGrid | None, float | None]:
    spaces = snap.spaces or []
    if not spaces:
        return None, None
    zone_map = _build_space_zone_map(snap)
    storey_map = _build_space_storey_map(snap)
    rows: list[list[Any]] = [list(_SPACE_HEADERS)]
    total = 0.0
    any_surface = False
    for sp in spaces:
        el = _rich(snap, sp)
        uuid = sp.get("uuid")
        surf, src = _surface_with_source(el, _SPACE_BQ_ORDER)
        if surf is not None:
            total += surf
            any_surface = True
        zone_val = _MULTI_SEP.join(zone_map.get(uuid, []))
        storeys = storey_map.get(uuid, [])
        if not storeys:
            direct = _storey(el)
            if direct:
                storeys = [direct]
        storey_val = _MULTI_SEP.join(storeys)
        rows.append(
            [
                "IfcSpace",
                _label(el),
                zone_val,
                storey_val,
                _ifc_type(el),
                surf,
                src or NOT_AVAILABLE,
            ]
        )
    return SheetGrid(title=title, rows=rows), (round(total, 4) if any_surface else None)


def build_shab_from_snapshot(snap: ModelSnapshot) -> tuple[MultiSheetSource | None, float | None]:
    """Export SHAB depuis la maquette : surfaces nettes des espaces."""
    grid, total = _spaces_grid(snap, "Export SHAB maquette (depuis maquette)")
    if grid is None:
        return None, None
    return MultiSheetSource(grids=[grid]), total


_ZONE_HEADERS = [
    "Zone (IfcZone)",
    "Libellé",
    "Étage(s)",
    "Nombre de pièces",
    "Surface (m²)",
    "Source surface",
]


def _zones_grid(snap: ModelSnapshot) -> SheetGrid:
    """Onglet Zones : une ligne par IfcZone, avec le(s) étage(s) traversé(s)
    (union des étages des pièces rattachées → duplex géré) et le nombre de
    pièces. Surface propre, sinon somme des espaces rattachés."""
    spaces = snap.spaces or []
    zones = snap.zones or []
    by_uuid = {sp.get("uuid"): _rich(snap, sp) for sp in spaces}
    storey_map = _build_space_storey_map(snap)
    rows: list[list[Any]] = [list(_ZONE_HEADERS)]
    for z in zones:
        zel = _rich(snap, z)
        members = _zone_member_uuids(z)
        if not members:
            members = [sp.get("uuid") for sp in spaces if _space_zone_uuid(sp) == z.get("uuid")]
        # Étage(s) couvert(s) par la zone = union des étages de ses pièces.
        storeys: list[str] = []
        for u in members:
            for name in storey_map.get(u, []):
                if name and name not in storeys:
                    storeys.append(name)
        surf, src = _surface_with_source(zel, _SPACE_BQ_ORDER)
        if surf is None:
            # Repli : somme des surfaces des espaces rattachés.
            acc = 0.0
            found = False
            for u in members:
                sp = by_uuid.get(u)
                if sp is None:
                    continue
                v, _ = _surface_with_source(sp, _SPACE_BQ_ORDER)
                if v is not None:
                    acc += v
                    found = True
            if found:
                surf, src = round(acc, 4), "Somme des espaces rattachés"
        rows.append(
            [
                _attr(z, "Name"),
                _label(zel),
                _MULTI_SEP.join(storeys),
                len(members) or None,
                surf,
                src or NOT_AVAILABLE,
            ]
        )
    return SheetGrid(title="Zones (depuis maquette)", rows=rows)


def build_zones_espaces_from_snapshot(snap: ModelSnapshot) -> MultiSheetSource | None:
    """Export Zones et Espaces depuis la maquette.

    **1er onglet = Zones (IfcZone)** avec étage(s) et nombre de pièces, puis
    l'onglet Espaces (pièces) avec leur zone et leur étage.
    """
    spaces = snap.spaces or []
    zones = snap.zones or []
    if not spaces and not zones:
        return None
    grids: list[SheetGrid] = []

    if zones:
        grids.append(_zones_grid(snap))

    if spaces:
        esp_grid, _ = _spaces_grid(snap, "Espaces (depuis maquette)")
        if esp_grid is not None:
            grids.append(esp_grid)

    return MultiSheetSource(grids=grids) if grids else None


def build_menuiseries_from_snapshot(
    snap: ModelSnapshot,
) -> tuple[MenuiseriesSource | None, float | None]:
    """Export Menuiseries depuis la maquette (IfcWindow + IfcDoor)."""
    items = list(snap.of_class("IfcWindow")) + list(snap.of_class("IfcDoor"))
    if not items:
        return None, None
    headers = [
        "Composant",
        "Type",
        "Matériau",
        "Largeur",
        "Hauteur",
        "Surface (m²)",
        "Source surface",
    ]
    rows: list[list[Any]] = []
    total = 0.0
    any_area = False
    types: set[str] = set()
    for w in items:
        width = _base_quantity_ordered(w, ("Width", "OverallWidth"))
        height = _base_quantity_ordered(w, ("Height", "OverallHeight"))
        surf, src = _surface_with_source(w, _WINDOW_BQ_AREA)
        if surf is None and width is not None and height is not None:
            surf, src = round(width * height, 4), "L×H (BaseQuantities)"
        if surf is not None:
            total += surf
            any_area = True
        ot = _ifc_type(w)
        if ot:
            types.add(ot)
        rows.append([_attr(w, "Name"), ot, _material(w), width, height, surf, src or NOT_AVAILABLE])
    table = SheetTable(title="Menuiseries", headers=headers, rows=rows)
    src = MenuiseriesSource(
        table=table,
        sheet_title="Menuiseries (depuis maquette)",
        nombre_types=(len(types) or None),
    )
    return src, (round(total, 4) if any_area else None)


_ENV_HEADERS = ["Composant", "Type", "Étage", "Layer", "Surface (m²)", "Source surface"]


def build_enveloppe_from_snapshot(snap: ModelSnapshot) -> EnveloppeSource | None:
    """Extraction surface enveloppe depuis la maquette (murs du layer cible)."""
    walls = _envelope_walls(snap)
    if not walls:
        return None
    rows: list[list[Any]] = []
    total = 0.0
    any_surface = False
    for w in walls:
        surf, src = _surface_with_source(w, _WALL_BQ_ORDER)
        if surf is not None:
            total += surf
            any_surface = True
        rows.append(
            [
                _attr(w, "Name"),
                _ifc_type(w),
                _storey(w),
                _ENVELOPE_LAYER,
                surf,
                src or NOT_AVAILABLE,
            ]
        )
    table = SheetTable(title="Extraction surface enveloppe", headers=list(_ENV_HEADERS), rows=rows)
    return EnveloppeSource(
        table=table,
        sheet_title="Surface enveloppe (depuis maquette)",
        superficie_facades=(round(total, 4) if any_surface else None),
    )


def build_sources_from_snapshot(snap: ModelSnapshot) -> AvpSources:
    """Construit un jeu de sources AVP **cohérent** depuis la maquette.

    Les grandeurs croisées (SHAB, superficie menuiseries, ratio FAC/SHAB)
    sont calculées uniquement quand les termes existent (jamais inventées).
    """
    shab_ms, shab_total = build_shab_from_snapshot(snap)
    zones_ms = build_zones_espaces_from_snapshot(snap)
    men_src, men_area = build_menuiseries_from_snapshot(snap)
    env_src = build_enveloppe_from_snapshot(snap)

    if env_src is not None:
        env_src.shab = shab_total
        env_src.superficie_menuiseries = men_area
        if env_src.superficie_facades is not None and shab_total:
            env_src.ratio_fac_shab = round(env_src.superficie_facades / shab_total, 4)

    return AvpSources(
        shab=shab_ms,
        zones_espaces=zones_ms,
        enveloppe=env_src,
        menuiseries=men_src,
    )
