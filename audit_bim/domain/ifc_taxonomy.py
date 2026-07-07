"""Table des sous-classes IFC pertinentes pour l'audit.

Le Cahier des Charges I3F référence des classes IFC « génériques » (IfcWall,
IfcSlab, IfcDoor, …). Les exports Revit/ArchiCAD produisent quasi-toujours
des **sous-classes spécialisées** (IfcWallStandardCase, IfcSlabStandardCase,
…) qui doivent hériter des exigences du parent.

Sans cette table, les centaines de IfcWallStandardCase ne seraient pas
auditées vs les exigences I3F (CODE, NetSideArea, Pset_WallCommon,
Pset_3F…), ce qui sous-évalue gravement les écarts au CCH.

La table reste **explicite et bornée** : on ne descend pas toute la hiérarchie
IFC, seulement les sous-classes effectivement émises par les outils CAO.
"""

from __future__ import annotations

# (parent IFC du CCH) → (sous-classes à inclure dans l'audit du parent)
IFC_SUBCLASSES: dict[str, list[str]] = {
    # Bâti
    "IfcWall": ["IfcWallStandardCase", "IfcWallElementedCase"],
    "IfcSlab": ["IfcSlabStandardCase", "IfcSlabElementedCase"],
    "IfcRoof": ["IfcRoofStandardCase"],
    "IfcDoor": ["IfcDoorStandardCase"],
    "IfcWindow": ["IfcWindowStandardCase"],
    "IfcBeam": ["IfcBeamStandardCase"],
    "IfcColumn": ["IfcColumnStandardCase"],
    "IfcMember": ["IfcMemberStandardCase"],
    "IfcPile": ["IfcPileStandardCase"],
    "IfcPlate": ["IfcPlateStandardCase"],
    "IfcStair": ["IfcStairStandardCase"],
    "IfcStairFlight": [],
    "IfcRamp": ["IfcRampStandardCase"],
    "IfcRampFlight": [],
    "IfcChimney": ["IfcChimneyStandardCase"],
    "IfcFooting": ["IfcFootingStandardCase"],
    "IfcRailing": ["IfcRailingStandardCase"],
    "IfcCovering": [],  # IfcCovering_CEILING etc. sont des suffixes I3F, pas IFC
    "IfcCurtainWall": [],
}


def expand_class(ifc_class: str) -> list[str]:
    """Retourne la classe + ses sous-classes connues, en préservant la classe parent en tête."""
    parent = ifc_class
    children = IFC_SUBCLASSES.get(parent, [])
    return [parent] + children


def normalize_catalog_class(raw: str) -> list[str]:
    """Normalise une étiquette de classe IFC issue de l'annexe Spécifications I3F.

    Cas particuliers observés :
    - ``"IfcDuctFittingType\\nIfcDuctSegmentType"`` → deux classes distinctes ;
    - ``"IfcCovering_CEILING"`` → IfcCovering (le suffixe est une discriminante
      d'usage I3F, pas une vraie classe IFC) ;
    - ``"ifcSlab"`` (casse différente) → IfcSlab ;
    - ``"IfcTendon\\nà défaut IfcBuildingElementProxy"`` → IfcTendon, fallback géré séparément.
    """
    if not raw:
        return []
    out: list[str] = []
    for chunk in raw.replace("\r", "").split("\n"):
        c = chunk.strip()
        if not c:
            continue
        # « à défaut IfcBuildingElementProxy » : fallback signalé par I3F,
        # on prend la classe (au cas où le modèle l'utilise) mais on garde
        # l'esprit en priorité sur le parent.
        if c.lower().startswith("à défaut"):
            tokens = c.split()
            for t in tokens:
                if t.lower().startswith("ifc"):
                    out.append(t)
                    break
            continue
        # Suffixe métier I3F (Covering_CEILING) → base IFC
        if "_" in c and c.lower().startswith("ifc"):
            c = c.split("_", 1)[0]
        # Normalise la casse Ifc*
        if c.lower().startswith("ifc") and not c.startswith("Ifc"):
            c = "Ifc" + c[3:]
        if c.lower().startswith("ifc"):
            out.append(c)
    # Dédup en gardant l'ordre
    seen, dedup = set(), []
    for c in out:
        if c not in seen:
            seen.add(c)
            dedup.append(c)
    return dedup
