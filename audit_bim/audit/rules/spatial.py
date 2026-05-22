"""Audit de la hiérarchie spatiale et des quantités requises (SHAB / SU)."""
from __future__ import annotations

from ...extraction.model_data import ModelSnapshot
from ...extraction.normalizer import get_attribute, resolve_value
from ...requirements.models import BIMPhase, RequirementsCatalog
from ..findings import ErrorType, Finding, Severity, Theme


def audit_spatial(
    snap: ModelSnapshot,
    catalog: RequirementsCatalog,
    phase: BIMPhase,
) -> list[Finding]:
    findings: list[Finding] = []

    # 1. Au moins un IfcSite, un IfcBuilding
    if not snap.sites and not snap.of_class("IfcSite"):
        findings.append(
            Finding(
                theme=Theme.SPATIAL_HIERARCHY,
                severity=Severity.CRITICAL,
                error_type=ErrorType.SPATIAL_ORPHAN,
                ifc_type="IfcSite",
                expected="≥ 1 IfcSite (programme)",
                actual=0,
                ref_cch="Chap 6.3.1",
                recommended_action="Modéliser au moins un IfcSite.",
            )
        )
    if not snap.buildings:
        findings.append(
            Finding(
                theme=Theme.SPATIAL_HIERARCHY,
                severity=Severity.CRITICAL,
                error_type=ErrorType.SPATIAL_ORPHAN,
                ifc_type="IfcBuilding",
                expected="≥ 1 IfcBuilding",
                actual=0,
                ref_cch="Chap 6.3.1",
                recommended_action="Modéliser au moins un bâtiment.",
            )
        )

    # 2. Étages présents
    if not snap.storeys:
        findings.append(
            Finding(
                theme=Theme.SPATIAL_HIERARCHY,
                severity=Severity.HIGH,
                error_type=ErrorType.SPATIAL_ORPHAN,
                ifc_type="IfcBuildingStorey",
                expected="≥ 1 IfcBuildingStorey",
                actual=0,
                ref_cch="Chap 6.3.1",
                recommended_action="Modéliser les étages du bâtiment.",
            )
        )

    # 3. Pièces (IfcSpace) attendues dès AVP
    if phase != BIMPhase.APS and not snap.spaces:
        findings.append(
            Finding(
                theme=Theme.SPATIAL_HIERARCHY,
                severity=Severity.HIGH,
                error_type=ErrorType.SPATIAL_ORPHAN,
                ifc_type="IfcSpace",
                expected=f"≥ 1 IfcSpace en phase {phase.value}",
                actual=0,
                ref_cch="Chap 6.3.2",
                recommended_action=(
                    "Modéliser les pièces (IfcSpace) du programme."
                ),
            )
        )

    # 4. Quantités IfcSpace : NetFloorArea / SHAB / SU attendues dès AVP
    if phase != BIMPhase.APS:
        for sp in snap.of_class("IfcSpace"):
            uuid = sp.get("uuid")
            nm = (
                get_attribute(sp, "LongName")
                or sp.get("longname")
                or get_attribute(sp, "Name")
                or sp.get("name")
            )
            # On cherche la surface (NetFloorArea ou GrossFloorArea)
            area = resolve_value(sp, "BaseQuantities", "NetFloorArea")
            if area is None:
                area = resolve_value(sp, "Pset_SpaceCommon", "GrossPlannedArea")
            if area in (None, 0, 0.0):
                findings.append(
                    Finding(
                        theme=Theme.QUANTITY,
                        severity=Severity.MEDIUM,
                        error_type=ErrorType.SPATIAL_MISSING_QUANTITY,
                        element_uuid=uuid,
                        ifc_type="IfcSpace",
                        name=str(nm) if nm else None,
                        expected="NetFloorArea (BaseQuantities) en m²",
                        actual=None,
                        ref_cch="Chap 6.2",
                        recommended_action=(
                            "Renseigner les quantités de surface (BaseQuantities)."
                        ),
                    )
                )

    # 5. Géoréférencement IfcSite (Latitude / Longitude) dès APS
    sites = snap.of_class("IfcSite") or snap.sites
    for site in sites:
        lat = (
            get_attribute(site, "RefLatitude")
            or get_attribute(site, "Latitude")
            or resolve_value(site, "Pset_SiteCommon", "RefLatitude")
        )
        lon = (
            get_attribute(site, "RefLongitude")
            or get_attribute(site, "Longitude")
            or resolve_value(site, "Pset_SiteCommon", "RefLongitude")
        )
        if lat in (None, "") or lon in (None, ""):
            findings.append(
                Finding(
                    theme=Theme.QUANTITY,
                    severity=Severity.MEDIUM,
                    error_type=ErrorType.PROPERTY_MISSING,
                    element_uuid=site.get("uuid"),
                    ifc_type="IfcSite",
                    name=get_attribute(site, "Name") or site.get("name"),
                    expected="IfcSite/Latitude + IfcSite/Longitude",
                    actual={"latitude": lat, "longitude": lon},
                    ref_cch="Chap 6.2",
                    recommended_action="Renseigner les coordonnées géographiques du site.",
                )
            )

    return findings
