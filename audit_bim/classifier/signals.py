"""Extraction des signaux exploitables sur un élément IFC (BIMData dénormalisé).

Les signaux fournissent du contexte pour heurister la classification quand
elle est manquante : nom de calque, attributs natifs, propriétés Pset, base
quantities, matériaux.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class ElementSignals:
    """Signaux normalisés extraits d'un élément BIMData."""

    ifc_class: str
    name: str = ""
    object_type: str = ""
    long_name: str = ""
    description: str = ""
    layers: list[str] = None  # noms de layers (Revit/CAO)
    materials: list[str] = None
    is_external: Optional[bool] = None
    load_bearing: Optional[bool] = None
    predefined_type: Optional[str] = None
    base_quantities: dict[str, float] = None  # NetSideArea, NetVolume, Height…

    def text_blob(self) -> str:
        """Bloc textuel agrégé pour matching keyword (en minuscules)."""
        parts = [
            self.name or "",
            self.object_type or "",
            self.long_name or "",
            self.description or "",
            " ".join(self.layers or []),
            " ".join(self.materials or []),
        ]
        return " ".join(parts).lower()

    def has_keyword(self, *keywords: str) -> bool:
        blob = self.text_blob()
        return any(k.lower() in blob for k in keywords)


# Psets dont on extrait les attributs structurants
_COMMON_PSETS = {
    "Pset_WallCommon",
    "Pset_SlabCommon",
    "Pset_DoorCommon",
    "Pset_WindowCommon",
    "Pset_RoofCommon",
    "Pset_BeamCommon",
    "Pset_ColumnCommon",
    "Pset_CoveringCommon",
    "Pset_RailingCommon",
    "Pset_StairCommon",
    "Pset_StairFlightCommon",
    "Pset_SpaceCommon",
    "Pset_BuildingCommon",
}


def _pset_value(element: dict, pset_name: str, prop_name: str):
    """Renvoie la valeur d'une propriété Pset, ou None."""
    for pset in element.get("property_sets") or []:
        pn = (pset.get("name") or "").lower()
        if pn == pset_name.lower() or pn.startswith(pset_name.lower()):
            for prop in pset.get("properties") or []:
                nm = (prop.get("definition") or {}).get("name") or ""
                if nm.lower() == prop_name.lower():
                    return prop.get("value")
    return None


def _base_quantities(element: dict) -> dict[str, float]:
    """Extrait les BaseQuantities (Pset 'BaseQuantities' ou 'Qto_*' ou 'Quantités_*')."""
    out: dict[str, float] = {}
    for pset in element.get("property_sets") or []:
        pn = (pset.get("name") or "")
        if not re.match(r"^(BaseQuantities|Qto_|Quantit)", pn, re.IGNORECASE):
            continue
        for prop in pset.get("properties") or []:
            nm = (prop.get("definition") or {}).get("name")
            val = prop.get("value")
            if nm and isinstance(val, (int, float)):
                out[nm] = float(val)
    return out


def _attr(element: dict, name: str) -> str:
    """Récupère un attribut natif et retourne une chaîne ('' si absent)."""
    v = element.get(name.lower()) or element.get(name)
    if v is None:
        # Cherche aussi dans 'attributes' (Pset des attributs natifs IFC)
        attrs = (element.get("attributes") or {}).get("properties") or []
        for prop in attrs:
            nm = (prop.get("definition") or {}).get("name") or ""
            if nm.lower() == name.lower():
                v = prop.get("value")
                break
    return "" if v is None else str(v)


def extract_signals(element: dict) -> ElementSignals:
    """Construit un ``ElementSignals`` depuis un élément BIMData dénormalisé."""
    layers = [
        l.get("name") or ""
        for l in (element.get("layers") or [])
        if isinstance(l, dict)
    ]
    materials = []
    for m in element.get("material_list") or []:
        mat = (m.get("material") or {}).get("name")
        if mat:
            materials.append(mat)

    bqty = _base_quantities(element)

    # Pset_*Common.IsExternal / LoadBearing : on cherche dans les Psets natifs
    is_external = None
    load_bearing = None
    for pname in _COMMON_PSETS:
        v = _pset_value(element, pname, "IsExternal")
        if v is not None and is_external is None:
            is_external = bool(v)
        v = _pset_value(element, pname, "LoadBearing")
        if v is not None and load_bearing is None:
            load_bearing = bool(v)

    predefined_type = _attr(element, "PredefinedType") or None

    return ElementSignals(
        ifc_class=element.get("type") or "",
        name=_attr(element, "Name") or (element.get("name") or ""),
        object_type=_attr(element, "ObjectType") or (element.get("object_type") or ""),
        long_name=_attr(element, "LongName") or (element.get("longname") or ""),
        description=_attr(element, "Description") or (element.get("description") or ""),
        layers=layers,
        materials=materials,
        is_external=is_external,
        load_bearing=load_bearing,
        predefined_type=predefined_type,
        base_quantities=bqty,
    )
