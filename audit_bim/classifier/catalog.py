"""Table de classification IFC → UniFormat II (référentiel par défaut).

UniFormat II (« UF ») est la classification fonctionnelle la plus utilisée en
France pour le BIM bâtiment. Elle organise les ouvrages par *systèmes*
(Substructure A, Shell B, Interiors C, Services D, Equipment & Furnishings E).

Cette table est volontairement **simple et bornée** — niveau 3 maximum.
Pour la personnaliser à votre table 3F interne, modifier ``ClassEntry`` ou
remplacer l'ensemble via le constructeur de ``ClassificationCatalog``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ClassEntry:
    """Une entrée de classification candidate."""

    code: str
    label: str
    system: str = "UniFormat II"

    def as_dict(self) -> dict:
        return {"code": self.code, "label": self.label, "system": self.system}


# Code → Label (UniFormat II Level 3)
UNIFORMAT: dict[str, str] = {
    "A1010": "Standard Foundations",
    "A1020": "Special Foundations",
    "A1030": "Slab on Grade",
    "A2010": "Basement Excavation",
    "A2020": "Basement Walls",
    "B1010": "Floor Construction",
    "B1020": "Roof Construction",
    "B2010": "Exterior Walls",
    "B2020": "Exterior Windows",
    "B2030": "Exterior Doors",
    "B3010": "Roof Coverings",
    "B3020": "Roof Openings",
    "C1010": "Partitions",
    "C1020": "Interior Doors",
    "C1030": "Fittings",
    "C2010": "Stair Construction",
    "C2020": "Stair Finishes",
    "C3010": "Wall Finishes",
    "C3020": "Floor Finishes",
    "C3030": "Ceiling Finishes",
    "D2010": "Plumbing Fixtures",
    "D2020": "Domestic Water Distribution",
    "D2030": "Sanitary Waste",
    "D3010": "Energy Supply",
    "D3020": "Heat Generating Systems",
    "D3030": "Cooling Generating Systems",
    "D3040": "Distribution Systems (HVAC)",
    "D3050": "Terminal & Package Units",
    "D3060": "Controls & Instrumentation",
    "D4010": "Sprinklers",
    "D4020": "Standpipes",
    "D5010": "Electrical Service",
    "D5020": "Lighting and Branch Wiring",
    "D5030": "Communications and Security",
    "D5090": "Other Electrical Systems",
    "E1010": "Commercial Equipment",
    "E2010": "Fixed Furnishings",
    "E2020": "Movable Furnishings",
}


def entry(code: str) -> ClassEntry:
    """Construit une ClassEntry depuis le code UniFormat."""
    return ClassEntry(code=code, label=UNIFORMAT.get(code, code))
