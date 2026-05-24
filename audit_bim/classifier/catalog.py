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


def normalize_uniformat_level3(code: str) -> str:
    """Réduit un code UniFormat au niveau 3 (5 caractères : <Lettre><4 chiffres>).

    UniFormat II structure :
    - Niveau 1 = lettre (A, B, C, D, E)
    - Niveau 2 = lettre + chiffre (A1, B2, C3…)
    - Niveau 3 = 5 caractères (B2010, C1010, E2020…)
    - Niveau 4+ = 6+ caractères, raffinements internes (E2020200…)

    Les classifications de maquette dépassent fréquemment le niveau 3 ; pour
    juger la *cohérence métier*, on compare uniquement les 5 premiers
    caractères. Tolérant aux séparateurs (« E2020.200 » → « E2020 »).

    Returns:
        Le code normalisé en majuscules, tronqué à 5 caractères. Chaîne vide
        si l'entrée n'est pas exploitable.
    """
    if not code:
        return ""
    s = str(code).strip().upper()
    # Retire séparateurs courants ("-", ".", " ", "_") pour ne garder que
    # les caractères significatifs.
    cleaned = "".join(ch for ch in s if ch.isalnum())
    return cleaned[:5]
