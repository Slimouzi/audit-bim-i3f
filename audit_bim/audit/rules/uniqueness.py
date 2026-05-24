"""Audit d'unicité — identifiant équipement obligatoire et unique.

Le CCH I3F (et les bonnes pratiques BIM en général) exigent que chaque
équipement physique (porte, fenêtre, terminal CVC, etc.) porte un
identifiant *unique* permettant son rapprochement avec la GMAO / DOE en
phase exploitation.

Critères de présence de l'identifiant, par ordre de priorité :
1. ``Pset_*Common.Tag`` — recommandé par buildingSMART pour les équipements.
2. ``Pset_*Common.Mark`` — couramment utilisé par Revit.
3. ``Tag`` natif IFC (attribut sur certaines classes).
4. ``Name`` (fallback) — accepté seulement si le suffixe numérique est unique.

La règle ne s'applique **qu'à partir de la phase DCE** (cohérent avec le
CCH) — avant, les équipements peuvent encore être génériques.
"""

from __future__ import annotations

from collections import Counter

from ...extraction.model_data import ModelSnapshot
from ...extraction.normalizer import get_attribute, resolve_value
from ...requirements.models import BIMPhase, RequirementsCatalog
from ..findings import ErrorType, Finding, Severity, Theme

# Classes IFC concernées par l'unicité (équipements physiques) — on cible
# les *terminaux* et *équipements*, pas les éléments constructifs continus
# (murs, dalles) qui n'ont pas besoin d'identifiant individuel en gestion.
_EQUIPMENT_CLASSES = {
    "IfcDoor",
    "IfcDoorStandardCase",
    "IfcWindow",
    "IfcWindowStandardCase",
    "IfcFurnishingElement",
    "IfcFlowTerminal",
    "IfcSanitaryTerminal",
    "IfcSanitaryTerminalType",
    "IfcAirTerminal",
    "IfcAirTerminalType",
    "IfcWasteTerminal",
    "IfcWasteTerminalType",
    "IfcFireSuppressionTerminal",
    "IfcFireSuppressionTerminalType",
    "IfcLamp",
    "IfcLampType",
    "IfcOutlet",
    "IfcOutletType",
    "IfcSwitchingDevice",
    "IfcSwitchingDeviceType",
    "IfcSensor",
    "IfcSensorType",
    "IfcController",
    "IfcControllerType",
    "IfcAlarm",
    "IfcAlarmType",
    "IfcValve",
    "IfcValveType",
    "IfcPump",
    "IfcPumpType",
    "IfcFan",
    "IfcFanType",
    "IfcDamper",
    "IfcDamperType",
    "IfcBoiler",
    "IfcBoilerType",
    "IfcUnitaryEquipment",
    "IfcUnitaryEquipmentType",
    "IfcElectricAppliance",
    "IfcElectricApplianceType",
    "IfcCableSegment",
    "IfcCableSegmentType",
    "IfcCableCarrierSegment",
    "IfcCableCarrierSegmentType",
    "IfcPipeSegment",
    "IfcPipeSegmentType",
    "IfcDuctSegment",
    "IfcDuctSegmentType",
}


def _equipment_identifier(element: dict) -> str | None:
    """Renvoie l'identifiant équipement le plus pertinent, ou ``None``."""
    for pset_root in ("Pset_DoorCommon", "Pset_WindowCommon", "Pset_FurnitureTypeCommon"):
        v = resolve_value(element, pset_root, "Tag")
        if v not in (None, ""):
            return str(v).strip()
        v = resolve_value(element, pset_root, "Mark")
        if v not in (None, ""):
            return str(v).strip()
    # Pset_*Common générique (tag/mark sur tout équipement)
    for pset in element.get("property_sets") or []:
        pname = pset.get("name") or ""
        if "Common" not in pname:
            continue
        for prop in pset.get("properties") or []:
            nm = ((prop.get("definition") or {}).get("name") or "").lower()
            if nm in ("tag", "mark"):
                val = prop.get("value")
                if val not in (None, ""):
                    return str(val).strip()
    # Attribut natif Tag
    tag = get_attribute(element, "Tag")
    if tag not in (None, ""):
        return str(tag).strip()
    return None


def audit_uniqueness(
    snap: ModelSnapshot,
    catalog: RequirementsCatalog,
    phase: BIMPhase,
) -> list[Finding]:
    """Vérifie que chaque équipement a un identifiant et qu'il est unique.

    Ne s'applique qu'à partir de la phase DCE (avant, équipements génériques OK).
    """
    findings: list[Finding] = []

    phase_order = {p: i for i, p in enumerate(BIMPhase.ordered())}
    if phase_order[phase] < phase_order[BIMPhase.DCE]:
        return findings

    # Collecte des identifiants par classe IFC (unicité par classe ; un Tag
    # peut être ré-utilisé dans deux classes différentes sans ambiguïté).
    by_class: dict[str, list[tuple[dict, str | None]]] = {}
    for ifc_class, elements in snap.elements_by_type.items():
        if ifc_class not in _EQUIPMENT_CLASSES:
            continue
        by_class[ifc_class] = [(el, _equipment_identifier(el)) for el in elements]

    for ifc_class, pairs in by_class.items():
        # 1. Présence
        for el, ident in pairs:
            if not ident:
                findings.append(
                    Finding(
                        theme=Theme.NAMING_SPACE,  # thème nommage générique
                        severity=Severity.MEDIUM,
                        error_type=ErrorType.NAMING_MISSING,
                        element_uuid=el.get("uuid"),
                        ifc_type=ifc_class,
                        name=get_attribute(el, "Name") or el.get("name"),
                        expected=(
                            "Identifiant équipement (Tag ou Mark) renseigné dans Pset_*Common"
                        ),
                        actual=None,
                        ref_cch="Chap 6.2 — équipements identifiables",
                        recommended_action=(
                            f"Renseigner Pset_{ifc_class[3:]}Common.Tag (ou Mark) "
                            "pour identification GMAO."
                        ),
                    )
                )

        # 2. Unicité (parmi ceux qui ont un identifiant)
        idents = [ident for _el, ident in pairs if ident]
        counts = Counter(idents)
        duplicates = {ident for ident, n in counts.items() if n > 1}
        if duplicates:
            for el, ident in pairs:
                if ident in duplicates:
                    findings.append(
                        Finding(
                            theme=Theme.NAMING_SPACE,
                            severity=Severity.MEDIUM,
                            error_type=ErrorType.NAMING_INVALID_FORMAT,
                            element_uuid=el.get("uuid"),
                            ifc_type=ifc_class,
                            name=get_attribute(el, "Name") or el.get("name"),
                            expected=(f"Identifiant unique parmi les {ifc_class}"),
                            actual=f"{ident!r} réutilisé {counts[ident]} fois",
                            ref_cch="Chap 6.2",
                            recommended_action=(
                                f"Renommer ou suffixer le Tag « {ident} » pour le rendre unique."
                            ),
                        )
                    )
    return findings
