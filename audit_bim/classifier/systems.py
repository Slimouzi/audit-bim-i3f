"""Référentiels de classification disponibles pour l'audit.

Chaque référentiel est défini par :
- son **nom** (envoyé à BIMData comme ``classification.name``),
- un **label** humain,
- un éventuel **mapper** ``ClassEntry → ClassEntry`` qui traduit un code
  UniFormat vers le code du référentiel cible. Par défaut, on conserve les
  codes UniFormat.

V1 : seul UniFormat II a une table complète. Les autres systèmes sont
listés comme « disponibles » (le suggester continue à utiliser UF II pour
ses heuristiques) — pour les passer en production, fournir la table de
correspondance via ``CUSTOM_MAPPERS``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .catalog import ClassEntry


@dataclass
class ClassificationSystem:
    """Référentiel disponible pour l'audit / la suggestion."""

    name: str  # nom court (transmis à l'API BIMData)
    label: str  # libellé humain
    description: str
    map_from_uniformat: Callable[[ClassEntry], ClassEntry] | None = None


# Mapping minimaliste UniFormat → Omniclass Table 22 (Work Results).
# À enrichir par projet — les correspondances ci-dessous sont indicatives.
_UF_TO_OMNICLASS_22: dict[str, tuple[str, str]] = {
    "B2010": ("21-02 10 10 10", "Exterior Walls"),
    "B2020": ("21-02 10 20 10", "Exterior Windows"),
    "B2030": ("21-02 10 30 10", "Exterior Doors"),
    "B1010": ("21-02 20 10 10", "Floor Construction"),
    "B1020": ("21-02 20 20 10", "Roof Construction"),
    "C1010": ("21-03 10 10 10", "Partitions"),
    "C1020": ("21-03 10 20 10", "Interior Doors"),
    "C2010": ("21-03 20 10 10", "Stair Construction"),
    "D2010": ("21-04 20 10 10", "Plumbing Fixtures"),
    "D3050": ("21-04 30 50 10", "Terminal & Package Units"),
    "D5020": ("21-04 50 20 10", "Lighting and Branch Wiring"),
    "E2010": ("21-05 20 10 10", "Fixed Furnishings"),
}


def _to_omniclass(uf: ClassEntry) -> ClassEntry:
    omni = _UF_TO_OMNICLASS_22.get(uf.code)
    if omni:
        return ClassEntry(code=omni[0], label=omni[1], system="Omniclass Table 22")
    # fallback : on garde le code UF mais on étiquette « Omniclass (sans
    # correspondance) » pour signaler à l'auditeur qu'il faut compléter.
    return ClassEntry(code=uf.code, label=uf.label, system="Omniclass (sans correspondance)")


SYSTEMS: dict[str, ClassificationSystem] = {
    "UniFormat II": ClassificationSystem(
        name="uniformat",
        label="UniFormat II",
        description=(
            "Classification fonctionnelle CSI/CSC — la plus utilisée en France "
            "pour le BIM bâtiment. Référentiel par défaut du MCP."
        ),
    ),
    "Omniclass": ClassificationSystem(
        name="omniclass",
        label="Omniclass Table 22 (Work Results)",
        description=(
            "Classification CSI Omniclass, table 22 (équivalente à MasterFormat). "
            "Table de correspondance UF II → Omniclass minimaliste — à compléter "
            "selon projet."
        ),
        map_from_uniformat=_to_omniclass,
    ),
    "CCS": ClassificationSystem(
        name="ccs",
        label="CCS (Cuneco Classification System)",
        description=(
            "Classification danoise / scandinave. Aucune table de correspondance "
            "auto — à fournir au cas par cas."
        ),
    ),
    "3F": ClassificationSystem(
        name="3f",
        label="Table 3F interne",
        description=(
            "Table de classification propre à I3F (gestion patrimoniale interne). "
            "À fournir au démarrage via un fichier ad hoc."
        ),
    ),
}


def get_system(name: str | None) -> ClassificationSystem:
    """Retourne le système nommé. Tolère diverses variantes (uniformat /
    UniFormat II / UF II)."""
    if not name:
        return SYSTEMS["UniFormat II"]
    nl = name.strip().lower()
    for key, s in SYSTEMS.items():
        if (
            key.lower() == nl
            or s.name == nl
            or s.label.lower() == nl
            or (nl == "uf" and key == "UniFormat II")
            or (nl == "uf ii" and key == "UniFormat II")
        ):
            return s
    raise ValueError(
        f"Système de classification inconnu : {name!r}. Disponibles : {list(SYSTEMS.keys())}."
    )


def translate(uf_entry: ClassEntry, target: ClassificationSystem) -> ClassEntry:
    """Traduit une ClassEntry UniFormat vers le référentiel cible."""
    if target.map_from_uniformat is None:
        return uf_entry  # même code, label adapté côté audit
    return target.map_from_uniformat(uf_entry)
