"""Heuristique de suggestion de classification UniFormat II.

Approche : pour chaque élément non classifié, on combine plusieurs signaux
(classe IFC × layer × attributs × Psets × BaseQuantities) pour proposer une
ou plusieurs entrées UniFormat avec un score de confiance pondéré.

L'objectif n'est *pas* d'avoir une précision parfaite (cela demanderait du
ML / un référentiel projet), mais de pré-mâcher le travail de l'AMO BIM :
proposer les 1-3 codes les plus probables, et signaler quand la maquette
fournit assez d'indices pour décider seul.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from .catalog import ClassEntry, entry
from .signals import ElementSignals


@dataclass
class Suggestion:
    """Une suggestion de classification avec sa traçabilité.

    Attributes:
        classification: Code + label + système (ClassEntry).
        confidence: Score 0..1 cumulé sur les signaux qui ont contribué.
        reasons: Liste lisible des signaux ayant pesé dans le score
            (exposée dans l'onglet xlsx ``Classifications suggérées``).
    """

    classification: ClassEntry
    confidence: float
    reasons: list[str]

    def as_dict(self) -> dict:
        """Sérialise la suggestion en dict JSON-compatible pour le MCP.

        Returns:
            Dict ``{code, label, system, confidence, reasons}``.
        """
        return {
            "code": self.classification.code,
            "label": self.classification.label,
            "system": self.classification.system,
            "confidence": round(self.confidence, 2),
            "reasons": self.reasons,
        }


# Pondérations des signaux
W_IFC_CLASS = 0.50  # mapping de base par classe IFC
W_LAYER = 0.20      # match du nom de calque
W_ATTRIBUTE = 0.15  # ObjectType / Name keyword
W_PSET = 0.10       # IsExternal / LoadBearing / PredefinedType
W_QUANTITY = 0.05   # BaseQuantities cohérentes


# ── Heuristiques layer (regex insensibles à la casse, recherche partielle) ──

# Famille de codes UniFormat acceptables pour une classe IFC ambigüe.
# Le suggester propose le code « le plus probable » (top 1) mais reconnaît
# que d'autres codes de la même famille sont aussi valides — utilisé pour la
# vérification de *cohérence* d'une classification existante (audit niveau 3).
IFC_ACCEPTED_CODES: dict[str, list[str]] = {
    # Mobilier : Fixed ou Movable, indifféremment plausibles
    "IfcFurnishingElement": ["E2010", "E2020"],
    # Revêtements intérieurs : sol, mur ou plafond selon PredefinedType
    "IfcCovering": ["C3010", "C3020", "C3030"],
    # Murs : intérieur ou extérieur selon IsExternal
    "IfcWall": ["B2010", "C1010"],
    "IfcWallStandardCase": ["B2010", "C1010"],
    "IfcWallElementedCase": ["B2010", "C1010"],
    # Portes : intérieures ou extérieures selon IsExternal
    "IfcDoor": ["B2030", "C1020"],
    "IfcDoorStandardCase": ["B2030", "C1020"],
    # Dalles : sol ou toiture selon PredefinedType
    "IfcSlab": ["B1010", "B1020"],
    "IfcSlabStandardCase": ["B1010", "B1020"],
    # IfcFlowTerminal très polyvalent (sanitaire, HVAC, lighting)
    "IfcFlowTerminal": ["D2010", "D3050", "D5020"],
}


def accepted_codes_for(ifc_class: str, top_code: Optional[str]) -> set[str]:
    """Famille de codes plausibles pour juger la cohérence d'une classification.

    Pour les classes IFC ambigües (mobilier fixe vs mobile, mur intérieur
    vs extérieur…), plusieurs codes UniFormat niveau 3 sont *légitimement*
    plausibles. Cette fonction donne l'ensemble accepté pour qu'une
    classification existante ne soit pas signalée incohérente alors
    qu'elle appartient à la même famille que le top suggéré.

    Args:
        ifc_class: Classe IFC réelle de l'élément (``IfcWallStandardCase``
            est traité comme ``IfcWall`` car les deux apparaissent comme
            clés dans ``IFC_ACCEPTED_CODES``).
        top_code: Top suggéré par ``suggest()`` (ajouté au set de retour).

    Returns:
        Set de codes UniFormat niveau 3 acceptés pour cette classe IFC
        (ex: ``{"E2010", "E2020"}`` pour ``IfcFurnishingElement``).
    """
    out: set[str] = set()
    if top_code:
        out.add(top_code.upper())
    for code in IFC_ACCEPTED_CODES.get(ifc_class, []):
        out.add(code.upper())
    return out


_LAYER_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b(mur[_\- ]?ext|exterior[_\- ]?wall|facade|fa[çc]ade)\b", re.I), "B2010"),
    (re.compile(r"\b(mur[_\- ]?int|partition|cloison|interior[_\- ]?wall)\b", re.I), "C1010"),
    (re.compile(r"\b(dalle|slab|plancher)\b", re.I), "B1010"),
    (re.compile(r"\b(toiture|roof|couverture)\b", re.I), "B1020"),
    (re.compile(r"\b(escalier|stair)\b", re.I), "C2010"),
    (re.compile(r"\b(porte[_\- ]?ext|exterior[_\- ]?door)\b", re.I), "B2030"),
    (re.compile(r"\b(porte[_\- ]?int|interior[_\- ]?door|porte)\b", re.I), "C1020"),
    (re.compile(r"\b(fen[êe]tre|window|baie[_\- ]?vitr)\b", re.I), "B2020"),
    (re.compile(r"\b(plafond|ceiling)\b", re.I), "C3030"),
    (re.compile(r"\b(rev[êe]tement[_\- ]?sol|floor[_\- ]?finish)\b", re.I), "C3020"),
    (re.compile(r"\b(rev[êe]tement[_\- ]?mur|wall[_\- ]?finish)\b", re.I), "C3010"),
    (re.compile(r"\b(mobilier|furniture|meuble|furnishing)\b", re.I), "E2010"),
    (re.compile(r"\b(garde[_\- ]?corps|railing|balustrade)\b", re.I), "C2010"),
    (re.compile(r"\b(sanitaire|plumbing|wc|lavabo|robinet)\b", re.I), "D2010"),
    (re.compile(r"\b(luminaire|lighting|\bled\b|spot)\b", re.I), "D5020"),
    (re.compile(r"\b(cvc|hvac|ventilation|clim)\b", re.I), "D3040"),
]

# ── Mapping IFC → UniFormat de base (avec branchements conditionnels) ──


def _ifc_base_code(s: ElementSignals) -> Optional[str]:
    """Code UniFormat principal déduit de la seule classe IFC + IsExternal."""
    c = s.ifc_class
    if c in ("IfcWall", "IfcWallStandardCase", "IfcWallElementedCase"):
        if s.is_external is True:
            return "B2010"
        if s.is_external is False:
            return "C1010"
        # Indéterminé → on tente C1010 (le cas le plus fréquent en logement)
        return "C1010"
    if c in ("IfcCurtainWall",):
        return "B2010"
    if c in ("IfcSlab", "IfcSlabStandardCase", "IfcSlabElementedCase"):
        pt = (s.predefined_type or "").upper()
        if pt == "ROOF":
            return "B1020"
        if pt in ("FLOOR", "BASESLAB"):
            return "B1010"
        return "B1010"
    if c in ("IfcRoof", "IfcRoofStandardCase"):
        return "B3010"
    if c in ("IfcDoor", "IfcDoorStandardCase"):
        return "B2030" if s.is_external else "C1020"
    if c in ("IfcWindow", "IfcWindowStandardCase"):
        return "B2020"
    if c in ("IfcColumn", "IfcColumnStandardCase"):
        return "B1010"  # éléments porteurs → structure
    if c in ("IfcBeam", "IfcBeamStandardCase"):
        return "B1010"
    if c in ("IfcFooting", "IfcFootingStandardCase"):
        return "A1010"
    if c in ("IfcPile", "IfcPileStandardCase"):
        return "A1020"
    if c in ("IfcStair", "IfcStairStandardCase", "IfcStairFlight"):
        return "C2010"
    if c in ("IfcRamp", "IfcRampStandardCase", "IfcRampFlight"):
        return "C2010"
    if c in ("IfcRailing", "IfcRailingStandardCase"):
        return "C2010"
    if c == "IfcCovering":
        pt = (s.predefined_type or "").upper()
        if pt == "CEILING" or s.has_keyword("plafond", "ceiling"):
            return "C3030"
        if pt == "FLOORING" or s.has_keyword("sol", "floor"):
            return "C3020"
        if pt in ("CLADDING", "INSULATION") or s.has_keyword("mur", "wall"):
            return "C3010"
        return "C3010"
    if c == "IfcFurnishingElement":
        return "E2010"
    if c in ("IfcSanitaryTerminal", "IfcSanitaryTerminalType"):
        return "D2010"
    if c in ("IfcFlowTerminal",):
        # ambigu : peut être sanitaire, terminal d'air ou électrique
        if s.has_keyword("lavabo", "wc", "vasque", "douche", "evier", "robinet"):
            return "D2010"
        if s.has_keyword("bouche", "ventilation", "diffuseur", "grille"):
            return "D3050"
        if s.has_keyword("luminaire", "spot", "led"):
            return "D5020"
        return "D3050"
    if c in ("IfcAirTerminal", "IfcAirTerminalType"):
        return "D3050"
    if c in ("IfcLight", "IfcLamp", "IfcLampType"):
        return "D5020"
    if c in ("IfcCableSegment", "IfcCableSegmentType",
             "IfcCableCarrierSegment", "IfcCableCarrierSegmentType",
             "IfcCableCarrierFitting", "IfcCableCarrierFittingType"):
        return "D5020"
    if c in ("IfcOutlet", "IfcOutletType"):
        return "D5020"
    if c in ("IfcSwitchingDevice", "IfcSwitchingDeviceType"):
        return "D5020"
    if c in ("IfcDuctSegment", "IfcDuctSegmentType",
             "IfcDuctFitting", "IfcDuctFittingType",
             "IfcDuctSilencer", "IfcDuctSilencerType",
             "IfcFan", "IfcFanType",
             "IfcDamper", "IfcDamperType"):
        return "D3040"
    if c in ("IfcPipeSegment", "IfcPipeSegmentType",
             "IfcPipeFitting", "IfcPipeFittingType",
             "IfcValve", "IfcValveType",
             "IfcPump", "IfcPumpType"):
        return "D2020"
    if c in ("IfcBoiler", "IfcBoilerType",
             "IfcCoil", "IfcCoilType",
             "IfcHeatExchanger", "IfcHeatExchangeType",
             "IfcSpaceHeater", "IfcSpaceHeaterType",
             "IfcElectricHeater", "IfcElectricHeaterType",
             "IfcUnitaryEquipmentType"):
        return "D3020"
    return None


def _layer_match(s: ElementSignals) -> Optional[tuple[str, str]]:
    """Cherche un layer dont le nom matche un pattern connu."""
    for layer in s.layers or []:
        for pattern, code in _LAYER_PATTERNS:
            if pattern.search(layer):
                return code, layer
    return None


def _keyword_match(s: ElementSignals) -> Optional[tuple[str, str]]:
    """Cherche des keywords dans Name / ObjectType / LongName."""
    blob = (s.name + " " + s.object_type + " " + s.long_name).lower()
    for pattern, code in _LAYER_PATTERNS:
        if pattern.search(blob):
            return code, blob[:60]
    return None


def _quantity_hint(s: ElementSignals, base_code: Optional[str]) -> Optional[str]:
    """Indice de cohérence basé sur les BaseQuantities (renvoie une raison)."""
    if not s.base_quantities:
        return None
    bq = s.base_quantities
    # Cas simple : un mur a typiquement NetSideArea et Height ; une dalle a
    # NetArea et GrossArea ; une porte a Width et Height (peu de surface).
    if base_code in ("B2010", "C1010") and ("NetSideArea" in bq or "Height" in bq):
        return "quantités cohérentes avec un mur (NetSideArea/Height présents)"
    if base_code in ("B1010", "B1020") and ("NetArea" in bq or "GrossArea" in bq):
        return "quantités cohérentes avec une dalle (NetArea/GrossArea présents)"
    if base_code in ("B2030", "C1020", "B2020") and "Width" in bq and "Height" in bq:
        return "quantités cohérentes avec une menuiserie (Width + Height)"
    return None


def suggest(element: dict, signals: Optional[ElementSignals] = None) -> list[Suggestion]:
    """Calcule les suggestions de classification UniFormat pour un élément.

    Agrège jusqu'à 5 signaux pondérés (cf. constantes ``W_*``). Le même
    code peut recevoir plusieurs contributions (classe IFC + layer +
    Pset…) : leurs poids s'additionnent (plafonné à 1.0) et les raisons
    sont accumulées dans ``Suggestion.reasons``.

    Args:
        element: Élément BIMData dénormalisé (cf. ``_denormalize_raw_elements``).
        signals: ``ElementSignals`` pré-calculés (optionnel — calculé
            depuis l'élément si absent).

    Returns:
        Liste de Suggestion triée par confiance décroissante. Vide si
        aucun code n'a pu être déduit (typique pour IfcBuildingElementProxy
        sans nom évocateur).
    """
    if signals is None:
        from .signals import extract_signals
        signals = extract_signals(element)

    suggestions: dict[str, Suggestion] = {}

    def add(code: str, weight: float, reason: str):
        if not code:
            return
        sug = suggestions.get(code)
        if sug is None:
            suggestions[code] = Suggestion(
                classification=entry(code),
                confidence=weight,
                reasons=[reason],
            )
        else:
            # Confiance plafonnée à 1
            sug.confidence = min(1.0, sug.confidence + weight)
            sug.reasons.append(reason)

    base = _ifc_base_code(signals)
    if base:
        add(base, W_IFC_CLASS, f"classe IFC = {signals.ifc_class}")

    lm = _layer_match(signals)
    if lm:
        add(lm[0], W_LAYER, f"layer match : « {lm[1]} »")

    km = _keyword_match(signals)
    if km:
        # Si le keyword match donne le même code que la classe, on ajoute juste
        # une raison de plus (sans doubler le poids) — sinon entrée distincte.
        add(km[0], W_ATTRIBUTE, f"mot-clé dans nom/type : « {km[1][:50]} »")

    if signals.is_external is True and base in ("B2010", "C1010"):
        add("B2010", W_PSET, "Pset_*Common.IsExternal = True")
    if signals.is_external is False and base in ("B2010", "C1010"):
        add("C1010", W_PSET, "Pset_*Common.IsExternal = False")

    if base:
        qty_reason = _quantity_hint(signals, base)
        if qty_reason:
            add(base, W_QUANTITY, qty_reason)

    return sorted(
        suggestions.values(), key=lambda s: -s.confidence
    )


def suggest_for_findings(
    findings: list,
    snap,
    *,
    min_confidence: float = 0.4,
    top_n: int = 3,
) -> list[dict]:
    """Génère les suggestions pour chaque finding ``classification_missing``.

    Adapté pour exposition MCP (sortie JSON-compatible).

    Args:
        findings: Liste de ``Finding`` (Pydantic) issus de l'audit. Seuls
            les findings ``error_type == "classification_missing"`` sont
            traités ; les autres sont ignorés.
        snap: ``ModelSnapshot`` (pour récupérer l'élément BIMData
            dénormalisé via ``element_by_uuid``).
        min_confidence: Seuil 0..1 sous lequel les suggestions sont
            exclues. Défaut 0.4 — relâcher pour avoir plus de
            propositions, ou monter pour réduire le bruit.
        top_n: Nombre max de suggestions par élément.

    Returns:
        Liste de dicts ``{element_uuid, ifc_type, name, layers, materials,
        is_external, suggestions: [{code, label, system, confidence,
        reasons}, ...]}`` — un par finding traité avec au moins une
        suggestion au-dessus du seuil.
    """
    out: list[dict] = []
    from .signals import extract_signals

    for f in findings:
        if f.error_type.value != "classification_missing":
            continue
        if not f.element_uuid:
            continue
        el = snap.element_by_uuid.get(f.element_uuid)
        if not el:
            continue
        signals = extract_signals(el)
        sugs = suggest(el, signals)
        sugs = [s for s in sugs if s.confidence >= min_confidence][:top_n]
        if not sugs:
            continue
        out.append({
            "element_uuid": f.element_uuid,
            "ifc_type": f.ifc_type,
            "name": f.name,
            "layers": signals.layers,
            "materials": signals.materials,
            "is_external": signals.is_external,
            "suggestions": [s.as_dict() for s in sugs],
        })
    return out
