"""Import des findings de l'audit préliminaire géométrique (MCP ifc-openshell).

Contrairement aux autres règles, ce module ne lit pas le snapshot BIMData :
il convertit les JSON produits par le serveur MCP ``ifc-openshell``
(dépôt « IFC Openshell » — clash ifcclash + inventaire pièces/zones) en
``Finding`` natifs, pour que les rapports Word/XLSX, les topics BCF et les
Smart Views les consomment sans modification.

Trois sources, toutes optionnelles :

- **inventaire** (``extract_space_inventory``) : flags pièce par pièce
  (trop petite, sans zone, sans surface, écart déclaré/recalculé), agrégats
  zones (typologie, continuité, doublons de nom), cohérence de nommage,
  fraîcheur du modèle.
- **clash espaces** (``run_space_clash_audit``) : doublons de pièces,
  chevauchements, placards double-modélisés, débordements verticaux.
- **pertes de surface** (``compute_surface_loss``) : m² perdus par pièce
  (murs/poteaux empiétants). Quand cette source est fournie, les entrées
  ``perte_de_surface`` brutes du clash espaces sont ignorées (redondantes
  et moins précises).
"""

from __future__ import annotations

from typing import Any

from ..findings import ErrorType, Finding, Severity, Theme

# Sévérité ifc-openshell ("Critique"/"Majeur"/"Mineur") → Severity native
_SEV_MAP = {
    "Critique": Severity.CRITICAL,
    "Majeur": Severity.HIGH,
    "Mineur": Severity.LOW,
}

# Provenance opposable des findings importés : un Finding sans ``ref_cch``
# n'est pas opposable au MOA (cf. audit.findings.Finding). Les contrôles
# géométriques n'ont pas de chapitre CCH dédié — on trace donc la source
# (audit préliminaire) et l'outil ifc-openshell qui l'a produit, plus le
# nom du fichier JSON quand il est connu.
_PROVENANCE = "Audit préliminaire géométrique — MCP ifc-openshell"
_SOURCE_TOOLS: dict[str, str] = {
    "inventory": "extract_space_inventory",
    "space_clash": "run_space_clash_audit",
    "surface_loss": "compute_surface_loss",
    "boundaries": "check_space_boundaries",
    "openings": "check_opening_correspondence",
}


def _stamp(
    findings: list[Finding], source_key: str, source_files: dict[str, str] | None
) -> list[Finding]:
    """Appose la provenance (``ref_cch``) sur les findings d'une source.

    Ne surcharge pas un ``ref_cch`` déjà renseigné. Inclut le nom du fichier
    JSON source si connu, pour une traçabilité complète.
    """
    ref = f"{_PROVENANCE} · {_SOURCE_TOOLS[source_key]}"
    fname = (source_files or {}).get(source_key)
    if fname:
        ref = f"{ref} · {fname}"
    return [f if f.ref_cch else f.model_copy(update={"ref_cch": ref}) for f in findings]


def _zone_of(space: dict) -> str | None:
    zones = space.get("zones") or []
    return zones[0] if zones else None


def _inventory_findings(inv: dict) -> list[Finding]:
    """Flags pièces + zones + nommage + fraîcheur → Findings."""
    findings: list[Finding] = []

    flag_specs: dict[str, tuple[Theme, ErrorType, Severity, str]] = {
        "piece_trop_petite": (
            Theme.QUANTITY,
            ErrorType.SPACE_TOO_SMALL,
            Severity.HIGH,
            "Vérifier la surface de la pièce (seuil réglementaire/décence).",
        ),
        "ecart_surface": (
            Theme.QUANTITY,
            ErrorType.QUANTITY_MISMATCH,
            Severity.MEDIUM,
            "Recalculer les quantités de la pièce (surface déclarée ≠ géométrie).",
        ),
        "sans_surface_declaree": (
            Theme.QUANTITY,
            ErrorType.SPATIAL_MISSING_QUANTITY,
            Severity.MEDIUM,
            "Exporter les BaseQuantities (NetFloorArea) de la pièce.",
        ),
        "sans_zone": (
            Theme.SPATIAL_HIERARCHY,
            ErrorType.SPACE_NO_ZONE,
            Severity.MEDIUM,
            "Rattacher la pièce à une zone (logement) via IfcRelAssignsToGroup.",
        ),
        "sans_etage": (
            Theme.SPATIAL_HIERARCHY,
            ErrorType.SPATIAL_ORPHAN,
            Severity.HIGH,
            "Rattacher la pièce à un IfcBuildingStorey.",
        ),
    }

    for sp in inv.get("spaces", []):
        for flag in sp.get("flags", []):
            spec = flag_specs.get(flag)
            if spec is None:
                continue
            theme, error_type, severity, action = spec
            expected: Any = None
            actual: Any = None
            if flag == "piece_trop_petite":
                expected = f">= {sp.get('min_area_threshold_m2')} m²"
                actual = f"{sp.get('area_declared_m2') or sp.get('area_recalc_m2')} m²"
            elif flag == "ecart_surface":
                expected = f"{sp.get('area_declared_m2')} m² (déclarée)"
                actual = (
                    f"{sp.get('area_recalc_m2')} m² recalculée ({sp.get('area_delta_pct'):+.1f} %)"
                )
            findings.append(
                Finding(
                    theme=theme,
                    severity=severity,
                    error_type=error_type,
                    element_uuid=sp.get("guid"),
                    ifc_type="IfcSpace",
                    name=sp.get("long_name") or sp.get("name"),
                    storey=sp.get("storey"),
                    zone=_zone_of(sp),
                    expected=expected,
                    actual=actual,
                    recommended_action=action,
                )
            )

    zone_specs: dict[str, tuple[ErrorType, Severity, str]] = {
        "typologie_incoherente": (
            ErrorType.ZONE_TYPOLOGY_MISMATCH,
            Severity.HIGH,
            "Aligner la typologie déclarée de la zone avec sa composition (nb chambres + 1).",
        ),
        "zone_discontinue": (
            ErrorType.ZONE_DISCONTINUITY,
            Severity.MEDIUM,
            "Vérifier le rattachement des pièces : zone répartie sur 3 étages ou plus.",
        ),
        "zone_sans_piece": (
            ErrorType.SPATIAL_ORPHAN,
            Severity.MEDIUM,
            "Supprimer la zone vide ou lui rattacher ses pièces.",
        ),
        "doublon_nom_zone": (
            ErrorType.ZONE_NAME_DUPLICATE,
            Severity.MEDIUM,
            "Renommer la zone : nom en doublon (légitime uniquement en duplex).",
        ),
    }
    for z in inv.get("zones", []):
        for flag in z.get("flags", []):
            spec = zone_specs.get(flag)
            if spec is None:  # duplex_possible = information, pas une anomalie
                continue
            error_type, severity, action = spec
            findings.append(
                Finding(
                    theme=Theme.SPATIAL_HIERARCHY,
                    severity=severity,
                    error_type=error_type,
                    element_uuid=z.get("guid"),
                    ifc_type="IfcZone",
                    name=z.get("name"),
                    zone=z.get("name"),
                    expected=z.get("typologie_declaree")
                    if flag == "typologie_incoherente"
                    else None,
                    actual=z.get("typologie_calculee") if flag == "typologie_incoherente" else None,
                    recommended_action=action,
                )
            )

    for issue in inv.get("naming_issues", []):
        findings.append(
            Finding(
                theme=Theme.NAMING_SPACE,
                severity=Severity.LOW,
                error_type=ErrorType.NAMING_INCONSISTENT,
                ifc_type="IfcSpace",
                name=issue.get("room_type"),
                expected="1 libellé par type de pièce",
                actual=", ".join(issue.get("variants", [])),
                recommended_action=(
                    f"Harmoniser les libellés du type de pièce '{issue.get('room_type')}'."
                ),
            )
        )

    dates = inv.get("dates") or {}
    if dates.get("stale"):
        findings.append(
            Finding(
                theme=Theme.DOCUMENT,
                severity=Severity.INFO,
                error_type=ErrorType.MODEL_STALE,
                name=inv.get("file"),
                expected=f"export < {dates.get('stale_after_days')} jours",
                actual=f"export du {dates.get('export_date')} ({dates.get('age_days')} jours)",
                recommended_action=("Demander un export IFC à jour avant de statuer sur l'audit."),
            )
        )

    return findings


# Classification clash espaces → (ErrorType, Severity, action recommandée).
# La sévérité est métier (impact sur les surfaces / le décompte des pièces),
# pas géométrique : un « Critique » ifcclash (type collision) ne vaut pas
# CRITICAL au sens du CCH.
_CLASH_SPECS: dict[str, tuple[ErrorType, Severity, str]] = {
    "doublon_piece": (
        ErrorType.SPACE_DUPLICATE,
        Severity.HIGH,
        "Supprimer la pièce en double (deux IfcSpace superposés au même étage).",
    ),
    "placard_double_modelise": (
        ErrorType.SPACE_DUPLICATE,
        Severity.HIGH,
        "Choisir une seule modélisation du placard : volume dans la pièce OU "
        "pièce dédiée, pas les deux.",
    ),
    "chevauchement_pieces": (
        ErrorType.SPACE_OVERLAP,
        Severity.MEDIUM,
        "Corriger les limites des deux pièces qui se chevauchent.",
    ),
    "chevauchement_vertical_entre_etages": (
        ErrorType.SPACE_VERTICAL_OVERLAP,
        Severity.MEDIUM,
        "Ajuster la hauteur de la pièce : elle traverse la dalle de l'étage supérieur.",
    ),
}


def _space_clash_findings(clash: dict) -> list[Finding]:
    """Findings du clash espaces (hors pertes de surface, couvertes par
    ``_surface_loss_findings``)."""
    findings: list[Finding] = []
    for item in clash.get("findings", []):
        classification = item.get("classification")
        spec = _CLASH_SPECS.get(classification)
        if spec is None:  # perte_de_surface → import via surface_loss
            continue
        error_type, severity, action = spec
        findings.append(
            Finding(
                theme=Theme.GEOMETRY,
                severity=severity,
                error_type=error_type,
                element_uuid=item.get("a_guid"),
                ifc_type="IfcSpace",
                name=item.get("a"),
                expected="pas de chevauchement entre pièces",
                actual=(f"{classification} avec {item.get('b')} (distance {item.get('distance')})"),
                recommended_action=action,
            )
        )
    return findings


def _surface_loss_findings(loss: dict) -> list[Finding]:
    """Pertes de surface par pièce → Findings (1 par pièce touchée)."""
    findings: list[Finding] = []
    for r in loss.get("losses", []):
        deduction = r.get("deduction_declaree") or {}
        declared = deduction.get("total_deduit_m2")
        actual = (
            f"{r.get('perte_totale_m2')} m² perdus "
            f"({r.get('perte_pct')} % — murs {r.get('perte_murs_m2')} m², "
            f"poteaux {r.get('perte_poteaux_m2')} m², "
            f"{r.get('n_intrus')} élément(s))"
        )
        if isinstance(declared, (int, float)):
            actual += f" ; déduction déclarée par l'architecte : {declared} m²"
        findings.append(
            Finding(
                theme=Theme.GEOMETRY,
                severity=_SEV_MAP.get(r.get("severity"), Severity.MEDIUM),
                error_type=ErrorType.SURFACE_LOSS,
                element_uuid=r.get("guid"),
                ifc_type="IfcSpace",
                name=r.get("long_name") or r.get("name"),
                storey=r.get("storey"),
                zone=_zone_of(r),
                expected="pièce sans empiétement mur/poteau",
                actual=actual,
                recommended_action=(
                    "Redessiner le contour de la pièce au nu fini des murs/poteaux "
                    "ou déclarer la déduction de surface."
                ),
            )
        )
    return findings


def _boundaries_findings(boundaries: dict) -> list[Finding]:
    """Limites manquantes entre pièces adjacentes → Findings."""
    findings: list[Finding] = []
    for m in boundaries.get("missing_boundaries", []):
        zones = m.get("zones") or []
        findings.append(
            Finding(
                theme=Theme.GEOMETRY,
                severity=Severity.HIGH,
                error_type=ErrorType.MISSING_SPACE_BOUNDARY,
                element_uuid=m.get("a_guid"),
                ifc_type="IfcSpace",
                name=m.get("a_name"),
                storey=m.get("storey"),
                zone=zones[0] if zones else None,
                expected="IfcRelSpaceBoundary entre pièces adjacentes",
                actual=(
                    f"aucune limite avec '{m.get('b_name')}' (distance {m.get('distance_m')} m)"
                ),
                recommended_action=(
                    "Régénérer les space boundaries ou fermer le volume entre "
                    f"'{m.get('a_name')}' et '{m.get('b_name')}'."
                ),
            )
        )
    for sp in boundaries.get("spaces_without_boundaries", []):
        findings.append(
            Finding(
                theme=Theme.GEOMETRY,
                severity=Severity.HIGH,
                error_type=ErrorType.SPACE_WITHOUT_BOUNDARIES,
                element_uuid=sp.get("guid"),
                ifc_type="IfcSpace",
                name=sp.get("name"),
                storey=sp.get("storey"),
                expected=">= 1 IfcRelSpaceBoundary par pièce",
                actual="aucune boundary",
                recommended_action=(
                    "Réexporter avec les space boundaries (vue d'export "
                    "'SpaceBoundary2ndLevelAddOnView' ou équivalent)."
                ),
            )
        )
    return findings


def _openings_findings(openings: dict) -> list[Finding]:
    """Correspondance ouvertures Archi ↔ Structure → Findings."""
    findings: list[Finding] = []

    if openings.get("structure_sans_reservations"):
        findings.append(
            Finding(
                theme=Theme.GEOMETRY,
                severity=Severity.HIGH,
                error_type=ErrorType.RESERVATIONS_NOT_MODELED,
                name=openings.get("structure"),
                expected="IfcOpeningElement pour chaque réservation structure",
                actual="0 IfcOpeningElement dans la maquette structure",
                recommended_action=(
                    "Demander au BET structure de modéliser les réservations en "
                    "IfcOpeningElement — le contrôle de correspondance avec "
                    "l'archi est impossible en l'état."
                ),
            )
        )
        return findings

    if openings.get("misaligned_models"):
        findings.append(
            Finding(
                theme=Theme.GEOMETRY,
                severity=Severity.HIGH,
                error_type=ErrorType.OPENING_MISMATCH,
                name=f"{openings.get('archi')} / {openings.get('structure')}",
                expected="maquettes archi et structure superposables",
                actual="emprises disjointes (bases de coordonnées différentes)",
                recommended_action=(
                    "Aligner les points de base projet des deux maquettes avant "
                    "tout contrôle inter-disciplines."
                ),
            )
        )
        return findings

    for o in openings.get("structure_sans_correspondance_archi", []):
        findings.append(
            Finding(
                theme=Theme.GEOMETRY,
                severity=Severity.HIGH,
                error_type=ErrorType.OPENING_MISMATCH,
                element_uuid=o.get("guid"),
                ifc_type="IfcOpeningElement",
                name=o.get("name") or o.get("host_name"),
                expected="ouverture archi correspondante "
                f"(tolérance {openings.get('tolerance_m')} m)",
                actual=(
                    f"ouverture structure dans {o.get('host_class')} "
                    f"'{o.get('host_name')}' sans équivalent archi"
                ),
                recommended_action=(
                    "Coordonner la réservation : reporter l'ouverture côté archi "
                    "ou supprimer la réservation structure obsolète."
                ),
            )
        )
    return findings


def load_preliminary_findings(
    inventory: dict | None = None,
    space_clash: dict | None = None,
    surface_loss: dict | None = None,
    boundaries: dict | None = None,
    openings: dict | None = None,
    source_files: dict[str, str] | None = None,
) -> list[Finding]:
    """Convertit les JSON du MCP ifc-openshell en Findings natifs.

    Chaque finding importé reçoit une provenance opposable dans ``ref_cch``
    (source « audit préliminaire géométrique » + outil ifc-openshell + nom
    du fichier JSON quand il est fourni via ``source_files``).

    Args:
        inventory: Sortie d'``extract_space_inventory`` (fichier
            ``*_space_inventory.json``).
        space_clash: Sortie de ``run_space_clash_audit`` (fichier
            ``*_space_clash_findings.json``).
        surface_loss: Sortie de ``compute_surface_loss`` (fichier
            ``*_surface_loss.json``).
        boundaries: Sortie de ``check_space_boundaries`` (fichier
            ``*_boundaries.json``).
        openings: Sortie de ``check_opening_correspondence`` (fichier
            ``*_openings_check.json``).
        source_files: Optionnel — noms des fichiers JSON par clé de source
            (``inventory``/``space_clash``/…) pour tracer l'origine dans
            ``ref_cch``.

    Returns:
        Findings prêts à être fusionnés dans un ``AuditResult``.
    """
    findings: list[Finding] = []
    if inventory:
        findings.extend(_stamp(_inventory_findings(inventory), "inventory", source_files))
    if space_clash:
        findings.extend(_stamp(_space_clash_findings(space_clash), "space_clash", source_files))
    if surface_loss:
        findings.extend(_stamp(_surface_loss_findings(surface_loss), "surface_loss", source_files))
    if boundaries:
        findings.extend(_stamp(_boundaries_findings(boundaries), "boundaries", source_files))
    if openings:
        findings.extend(_stamp(_openings_findings(openings), "openings", source_files))
    return findings
