"""Audit du nommage IFC selon CCH I3F V3.x — chap 6.3.1 / 6.3.2."""

from __future__ import annotations

import re

from ...domain.text import fold_upper
from ...extraction.model_data import ModelSnapshot
from ...extraction.normalizer import get_attribute
from ...requirements.models import RequirementsCatalog
from ..findings import ErrorType, Finding, Severity, Theme


def _check_storey_name(name: str | None, allowed: set[str]) -> bool:
    """Tolère les suffixes numériques (TOITURE 02, ENTRESOL 03, etc.).

    Comparaison **insensible aux accents** : ``allowed`` doit être construit via
    :func:`fold_upper` (cf. ``audit_naming``) et ``name`` l'est ici — sinon
    ``1ER ÉTAGE`` ≠ ``1ER ETAGE`` produit un faux ``NAMING_NOT_IN_LIST``.
    """
    if not name:
        return False
    n = fold_upper(name)
    if n in allowed:
        return True
    # Tolérance suffixes
    for base in ("TOITURE", "ENTRESOL", "COMBLES"):
        if base in allowed and re.fullmatch(rf"{base}(\s+\d{{1,2}})?", n):
            return True
    return False


def _check_room_name(name: str | None, allowed: set[str]) -> bool:
    """Tolère « CHAMBRE 01 » (base + suffixe numérique optionnel).

    Insensible aux accents (cf. :func:`_check_storey_name`)."""
    if not name:
        return False
    n = fold_upper(name)
    if n in allowed:
        return True
    base = re.sub(r"\s+\d{1,3}$", "", n)
    return base in allowed


def audit_naming(
    snap: ModelSnapshot,
    catalog: RequirementsCatalog,
    phase: object = None,
) -> list[Finding]:
    """Audit IfcProject/Site/Building/Storey + IfcZone + IfcSpace.

    ``phase`` est accepté (et **ignoré**) pour satisfaire le protocole ``Rule``
    ``(snap, catalog, phase) -> list[Finding]`` du moteur générique
    ``bim-audit-engine`` : le nommage CCH ne dépend pas de la phase, mais la
    règle doit avoir la même signature que les autres pour être injectée.
    """
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
                    field_path="IfcProject.LongName",
                    actual=f"{len(project_name)} caractères",
                    ref_cch=rule.ref_cch,
                    recommended_action="Raccourcir le LongName du projet.",
                )
            )

    # ── IfcSite (Name) ──────────────────────────────────────────────────────
    rule = catalog.naming_rule_for("IfcSite", "Name")
    for site in snap.of_class("IfcSite"):
        nm = get_attribute(site, "Name") or site.get("name")
        if not nm:
            # La codification du site (ex: 1802L) est la clé de l'arbre I3F :
            # un Name absent doit être signalé comme les autres niveaux
            # (Building/Storey/Zone/Space l'étaient déjà, pas le Site).
            findings.append(
                Finding(
                    theme=Theme.NAMING_SITE_BAT_ETAGE,
                    severity=Severity.HIGH,
                    error_type=ErrorType.NAMING_MISSING,
                    element_uuid=site.get("uuid"),
                    ifc_type="IfcSite",
                    expected="Codification du site (ex: 1802L, 1802P)",
                    actual=None,
                    ref_cch=rule.ref_cch if rule else "Chap 6.3.1",
                    recommended_action="Renseigner IfcSite/Name selon la codification 3F.",
                    field_path="IfcSite.Name",
                )
            )
            continue
        if rule and rule.pattern and not re.fullmatch(rule.pattern, str(nm)):
            findings.append(
                Finding(
                    theme=Theme.NAMING_SITE_BAT_ETAGE,
                    severity=Severity.HIGH,
                    error_type=ErrorType.NAMING_INVALID_FORMAT,
                    element_uuid=site.get("uuid"),
                    ifc_type="IfcSite",
                    name=nm,
                    expected=f"Pattern {rule.pattern} (ex: 1802L, 1802P)",
                    field_path="IfcSite.Name",
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
                    field_path="IfcBuilding.Name",
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
                    field_path="IfcBuilding.Name",
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
                    field_path="IfcBuilding.Name",
                    ref_cch=rule.ref_cch,
                    recommended_action="Raccourcir le nom du bâtiment.",
                )
            )

    # ── IfcBuildingStorey (Name vs liste fermée) ────────────────────────────
    rule = catalog.naming_rule_for("IfcBuildingStorey", "Name")
    allowed_storeys = {fold_upper(s.name) for s in catalog.storey_names}
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
                    field_path="IfcBuildingStorey.Name",
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
                    field_path="IfcBuildingStorey.Name",
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
                    field_path="IfcZone.Name",
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
                    field_path="IfcZone.Name",
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
                    field_path="IfcZone.ObjectType",
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
                    field_path="IfcZone.ObjectType",
                )
            )

    # ── IfcSpace (LongName vs liste pièces) ─────────────────────────────────
    # Repli LongName → Name : certains outils auteurs (ArchiCAD) remplissent
    # Name là où le CCH attend LongName. La donnée trouvée dans Name satisfait
    # le contrôle de contenu, mais le mauvais emplacement est signalé en LOW
    # (au lieu du HIGH « manquant »).
    rule_space = catalog.naming_rule_for("IfcSpace", "LongName")
    allowed_rooms = {fold_upper(r.name) for r in catalog.room_specs}
    for sp in snap.of_class("IfcSpace"):
        ln = get_attribute(sp, "LongName") or sp.get("longname")
        from_name_fallback = False
        if not ln:
            ln = get_attribute(sp, "Name") or sp.get("name")
            from_name_fallback = bool(ln)
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
                    field_path="IfcSpace.LongName",
                )
            )
            continue
        if from_name_fallback:
            findings.append(
                Finding(
                    theme=Theme.NAMING_SPACE,
                    severity=Severity.LOW,
                    error_type=ErrorType.NAMING_INVALID_FORMAT,
                    element_uuid=sp.get("uuid"),
                    ifc_type="IfcSpace",
                    name=str(ln).strip(),
                    expected="Nom de pièce porté par IfcSpace/LongName",
                    actual=f"trouvé dans IfcSpace/Name : '{str(ln).strip()}' (LongName vide)",
                    field_path="IfcSpace.LongName",
                    ref_cch=rule_space.ref_cch if rule_space else "Chap 6.3.2",
                    recommended_action=(
                        "Remapper l'export (Name → LongName) — la donnée existe "
                        "mais n'est pas à l'emplacement attendu par le CCH."
                    ),
                )
            )
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
                    field_path="IfcSpace.LongName",
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
                    field_path="IfcSpace.LongName",
                )
            )

    return findings
