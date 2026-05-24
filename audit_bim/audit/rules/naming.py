"""Audit du nommage IFC selon CCH I3F V3.x — chap 6.3.1 / 6.3.2."""

from __future__ import annotations

import re

from ...extraction.model_data import ModelSnapshot
from ...extraction.normalizer import get_attribute
from ...requirements.models import RequirementsCatalog
from ..findings import ErrorType, Finding, Severity, Theme


def _check_storey_name(name: str | None, allowed: set[str]) -> bool:
    """Tolère les suffixes numériques (TOITURE 02, ENTRESOL 03, etc.)."""
    if not name:
        return False
    n = name.strip().upper()
    if n in allowed:
        return True
    # Tolérance suffixes
    for base in ("TOITURE", "ENTRESOL", "COMBLES"):
        if base in allowed and re.fullmatch(rf"{base}(\s+\d{{1,2}})?", n):
            return True
    return False


def _check_room_name(name: str | None, allowed: set[str]) -> bool:
    """Tolère « CHAMBRE 01 » (base + suffixe numérique optionnel)."""
    if not name:
        return False
    n = name.strip().upper()
    if n in allowed:
        return True
    base = re.sub(r"\s+\d{1,3}$", "", n)
    return base in allowed


def audit_naming(snap: ModelSnapshot, catalog: RequirementsCatalog) -> list[Finding]:
    """Audit IfcProject/Site/Building/Storey + IfcZone + IfcSpace."""
    findings: list[Finding] = []

    # ── IfcProject (LongName) ───────────────────────────────────────────────
    rule = catalog.naming_rule_for("IfcProject", "LongName")
    project_name = (snap.project or {}).get("name")
    if rule and project_name:
        if rule.max_length and len(project_name) > rule.max_length:
            findings.append(
                Finding(
                    theme=Theme.NAMING_SITE_BAT_ETAGE,
                    severity=Severity.LOW,
                    error_type=ErrorType.NAMING_TOO_LONG,
                    ifc_type="IfcProject",
                    name=project_name,
                    expected=f"≤ {rule.max_length} caractères",
                    actual=f"{len(project_name)} caractères",
                    ref_cch=rule.ref_cch,
                    recommended_action="Raccourcir le LongName du projet.",
                )
            )

    # ── IfcSite (Name) ──────────────────────────────────────────────────────
    rule = catalog.naming_rule_for("IfcSite", "Name")
    for site in snap.of_class("IfcSite"):
        nm = get_attribute(site, "Name") or site.get("name")
        if rule and rule.pattern and nm and not re.fullmatch(rule.pattern, str(nm)):
            findings.append(
                Finding(
                    theme=Theme.NAMING_SITE_BAT_ETAGE,
                    severity=Severity.HIGH,
                    error_type=ErrorType.NAMING_INVALID_FORMAT,
                    element_uuid=site.get("uuid"),
                    ifc_type="IfcSite",
                    name=nm,
                    expected=f"Pattern {rule.pattern} (ex: 1802L, 1802P)",
                    actual=nm,
                    ref_cch=rule.ref_cch,
                    recommended_action="Renommer le site selon la codification 3F.",
                )
            )

    # ── IfcBuilding (Name) ──────────────────────────────────────────────────
    rule = catalog.naming_rule_for("IfcBuilding", "Name")
    for bld in snap.of_class("IfcBuilding"):
        nm = get_attribute(bld, "Name") or bld.get("name")
        if not nm:
            findings.append(
                Finding(
                    theme=Theme.NAMING_SITE_BAT_ETAGE,
                    severity=Severity.HIGH,
                    error_type=ErrorType.NAMING_MISSING,
                    element_uuid=bld.get("uuid"),
                    ifc_type="IfcBuilding",
                    expected="Nom du bâtiment (ex: 1802L-A)",
                    actual=None,
                    ref_cch=rule.ref_cch if rule else "Chap 6.3.1",
                    recommended_action="Renseigner IfcBuilding/Name.",
                )
            )
            continue
        if rule and rule.pattern and not re.fullmatch(rule.pattern, str(nm)):
            findings.append(
                Finding(
                    theme=Theme.NAMING_SITE_BAT_ETAGE,
                    severity=Severity.MEDIUM,
                    error_type=ErrorType.NAMING_INVALID_FORMAT,
                    element_uuid=bld.get("uuid"),
                    ifc_type="IfcBuilding",
                    name=nm,
                    expected=f"Pattern {rule.pattern} (ex: 1802L-A)",
                    actual=nm,
                    ref_cch=rule.ref_cch,
                    recommended_action="Renommer le bâtiment.",
                )
            )
        if rule and rule.max_length and len(str(nm)) > rule.max_length:
            findings.append(
                Finding(
                    theme=Theme.NAMING_SITE_BAT_ETAGE,
                    severity=Severity.LOW,
                    error_type=ErrorType.NAMING_TOO_LONG,
                    element_uuid=bld.get("uuid"),
                    ifc_type="IfcBuilding",
                    name=nm,
                    expected=f"≤ {rule.max_length} car.",
                    actual=f"{len(str(nm))} car.",
                    ref_cch=rule.ref_cch,
                    recommended_action="Raccourcir le nom du bâtiment.",
                )
            )

    # ── IfcBuildingStorey (Name vs liste fermée) ────────────────────────────
    rule = catalog.naming_rule_for("IfcBuildingStorey", "Name")
    allowed_storeys = {s.name.upper() for s in catalog.storey_names}
    for st in snap.of_class("IfcBuildingStorey"):
        nm = get_attribute(st, "Name") or st.get("name")
        if not nm:
            findings.append(
                Finding(
                    theme=Theme.NAMING_SITE_BAT_ETAGE,
                    severity=Severity.HIGH,
                    error_type=ErrorType.NAMING_MISSING,
                    element_uuid=st.get("uuid"),
                    ifc_type="IfcBuildingStorey",
                    expected="REZ-DE-CHAUSSEE / 1ER ETAGE / 2EME ETAGE …",
                    actual=None,
                    ref_cch=rule.ref_cch if rule else "Chap 6.3.1",
                    recommended_action="Renseigner IfcBuildingStorey/Name.",
                )
            )
            continue
        if allowed_storeys and not _check_storey_name(str(nm), allowed_storeys):
            findings.append(
                Finding(
                    theme=Theme.NAMING_SITE_BAT_ETAGE,
                    severity=Severity.MEDIUM,
                    error_type=ErrorType.NAMING_NOT_IN_LIST,
                    element_uuid=st.get("uuid"),
                    ifc_type="IfcBuildingStorey",
                    name=str(nm),
                    expected=sorted(allowed_storeys),
                    actual=str(nm),
                    ref_cch=rule.ref_cch if rule else "Chap 6.3.1",
                    recommended_action="Aligner le nom de l'étage sur la liste du CCH.",
                )
            )

    # ── IfcZone (Name + ObjectType) ─────────────────────────────────────────
    # Le CCH I3F (chap 6.3.2) distingue deux régimes :
    #  - Parties Privatives (PP) : zones logement → Name doit suivre le
    #    pattern XXXXL-YYYY (ex: 7427L-1103).
    #  - Parties Communes (PC) : PARKINGS, PARTIE COMMUNE 01, TECHNIQUE,
    #    TOITURE TERRASSE, etc. → pas de format imposé sur le Name.
    # On détermine la localisation depuis l'ObjectType, qui doit nommer
    # explicitement la typologie (« Zone Logement T3 », « Zone Parkings »…).
    rule_zone_name = catalog.naming_rule_for("IfcZone", "Name")
    allowed_zone_types = {z.type_label.strip() for z in catalog.zone_specs if z.type_label}

    def _is_dwelling_zone(object_type: str | None) -> bool:
        """Vrai si l'ObjectType de la zone est une partie privative logement."""
        if not object_type:
            return False
        ot_lower = str(object_type).strip().lower()
        # « Zone Logement T2 », « Zone Lgt autre propr. », etc.
        return "logement" in ot_lower or "lgt" in ot_lower

    for z in snap.of_class("IfcZone"):
        nm = get_attribute(z, "Name") or z.get("name")
        ot = get_attribute(z, "ObjectType") or z.get("object_type")
        is_dwelling = _is_dwelling_zone(ot)

        if not nm:
            findings.append(
                Finding(
                    theme=Theme.NAMING_ZONE,
                    severity=Severity.HIGH,
                    error_type=ErrorType.NAMING_MISSING,
                    element_uuid=z.get("uuid"),
                    ifc_type="IfcZone",
                    expected="Nom usuel du logement (ex: 1802L-1101)",
                    actual=None,
                    ref_cch="Chap 6.3.2.1",
                    recommended_action="Renseigner IfcZone/Name.",
                )
            )
        elif is_dwelling and (
            rule_zone_name
            and rule_zone_name.pattern
            and not re.fullmatch(rule_zone_name.pattern, str(nm))
        ):
            # Pattern XXXXL-YYYY exigé uniquement pour les zones logement (PP).
            # Pour les Parties Communes (PARKINGS, PARTIE COMMUNE 01,
            # TECHNIQUE, TOITURE TERRASSE…), aucun format de Name n'est
            # imposé par le CCH → on ne signale rien.
            findings.append(
                Finding(
                    theme=Theme.NAMING_ZONE,
                    severity=Severity.MEDIUM,
                    error_type=ErrorType.NAMING_INVALID_FORMAT,
                    element_uuid=z.get("uuid"),
                    ifc_type="IfcZone",
                    name=str(nm),
                    expected="Pattern XXXXL-YYYY pour les zones logement",
                    actual=str(nm),
                    ref_cch="Chap 6.3.2.1",
                    recommended_action="Renommer la zone selon le format I3F.",
                )
            )

        if not ot:
            findings.append(
                Finding(
                    theme=Theme.NAMING_ZONE,
                    severity=Severity.HIGH,
                    error_type=ErrorType.NAMING_MISSING,
                    element_uuid=z.get("uuid"),
                    ifc_type="IfcZone",
                    name=str(nm) if nm else None,
                    expected="IfcZone/ObjectType obligatoire (Zone Logement T2, Zone Bureaux…)",
                    actual=None,
                    ref_cch="Chap 6.3.2",
                    recommended_action="Renseigner IfcZone/ObjectType.",
                )
            )
        elif allowed_zone_types and str(ot).strip() not in allowed_zone_types:
            findings.append(
                Finding(
                    theme=Theme.NAMING_ZONE,
                    severity=Severity.MEDIUM,
                    error_type=ErrorType.NAMING_NOT_IN_LIST,
                    element_uuid=z.get("uuid"),
                    ifc_type="IfcZone",
                    name=str(nm) if nm else None,
                    expected=sorted(allowed_zone_types),
                    actual=str(ot),
                    ref_cch="Chap 6.3.2",
                    recommended_action="Aligner le ObjectType de la zone sur la liste I3F.",
                )
            )

    # ── IfcSpace (LongName vs liste pièces) ─────────────────────────────────
    rule_space = catalog.naming_rule_for("IfcSpace", "LongName")
    allowed_rooms = {r.name.upper().strip() for r in catalog.room_specs}
    for sp in snap.of_class("IfcSpace"):
        ln = get_attribute(sp, "LongName") or sp.get("longname")
        if not ln:
            findings.append(
                Finding(
                    theme=Theme.NAMING_SPACE,
                    severity=Severity.HIGH,
                    error_type=ErrorType.NAMING_MISSING,
                    element_uuid=sp.get("uuid"),
                    ifc_type="IfcSpace",
                    expected="Nom de pièce en majuscules (ex: CHAMBRE 01)",
                    actual=None,
                    ref_cch=rule_space.ref_cch if rule_space else "Chap 6.3.2",
                    recommended_action="Renseigner IfcSpace/LongName.",
                )
            )
            continue
        ln_str = str(ln).strip()
        if rule_space and rule_space.case_sensitive and ln_str != ln_str.upper():
            findings.append(
                Finding(
                    theme=Theme.NAMING_SPACE,
                    severity=Severity.LOW,
                    error_type=ErrorType.NAMING_INVALID_FORMAT,
                    element_uuid=sp.get("uuid"),
                    ifc_type="IfcSpace",
                    name=ln_str,
                    expected="Majuscules",
                    actual=ln_str,
                    ref_cch=rule_space.ref_cch,
                    recommended_action="Passer le LongName en majuscules.",
                )
            )
        if allowed_rooms and not _check_room_name(ln_str, allowed_rooms):
            findings.append(
                Finding(
                    theme=Theme.NAMING_SPACE,
                    severity=Severity.MEDIUM,
                    error_type=ErrorType.NAMING_NOT_IN_LIST,
                    element_uuid=sp.get("uuid"),
                    ifc_type="IfcSpace",
                    name=ln_str,
                    expected=sorted(allowed_rooms)[:30] + ["…"],
                    actual=ln_str,
                    ref_cch="Chap 6.3.2",
                    recommended_action="Renommer la pièce avec un libellé du CCH.",
                )
            )

    return findings
