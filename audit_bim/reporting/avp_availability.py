"""Vérification de disponibilité des rapports XLS AVP I3F.

Pour chaque rapport du catalogue (:mod:`avp_report_catalog`), on **sonde**
réellement le ``ModelSnapshot`` (entités IFC, BaseQuantities, relations
zone/espace, calque d'enveloppe) et les sources XLS éventuellement fournies,
puis on rend un verdict orienté utilisateur :

- ``can_generate`` : un rapport **métier** exploitable est produisible ;
- ``can_generate_identical`` : la reproduction MOA **stricte** est possible
  (toutes les colonnes, y compris Solibri/source externe, disponibles) ;
- ``status`` : ``ready`` / ``partial`` / ``blocked`` ;
- ``available_data`` / ``missing_data`` : détail par donnée requise.

Position CTO respectée : on **ne promet pas** « à l'identique » quand une
donnée ``external`` (Solibri) est absente — ``can_generate_identical`` reste
``False`` et le rapport passe au mieux en ``partial``.
"""

from __future__ import annotations

from ..extraction.model_data import ModelSnapshot
from .avp_report_catalog import (
    REPORT_SPECS,
    DataRequirement,
    ReportAvailability,
    ReportSpec,
)
from .avp_snapshot import (
    _base_quantity_ordered,
    _rich,
    _space_zone_uuid,
    _zone_member_uuids,
    _zone_members_from_tree,
    count_envelope_walls,
)


def _has_ifc_entity(snap: ModelSnapshot, classes: tuple[str, ...]) -> bool:
    return any(snap.of_class(c) for c in classes)


def _has_base_quantity(snap: ModelSnapshot, classes: tuple[str, ...], quantity: str) -> bool:
    """Vrai si **au moins une** entité des classes porte la BaseQuantity nommée."""
    for cls in classes:
        for el in snap.of_class(cls):
            if _base_quantity_ordered(_rich(snap, el), (quantity,)) is not None:
                return True
    return False


def _has_zone_space_relation(snap: ModelSnapshot) -> bool:
    """Vrai si au moins une IfcZone est rattachée à des espaces (liste directe,
    référence inverse espace→zone, ou arborescence spatiale)."""
    zones = snap.zones or []
    if not zones:
        return False
    spaces = snap.spaces or []
    tree_members = _zone_members_from_tree(snap)
    for z in zones:
        if _zone_member_uuids(z):
            return True
        zuuid = z.get("uuid")
        if zuuid and any(_space_zone_uuid(sp) == zuuid for sp in spaces):
            return True
        if tree_members.get(zuuid):
            return True
    return False


def _source_present(sources, deliverable_key: str) -> bool:
    """Vrai si une source XLS MOA est chargée pour ce livrable (satisfait les
    colonnes externes Solibri)."""
    if sources is None:
        return False
    src = getattr(sources, deliverable_key, None)
    if src is None:
        return False
    # MultiSheetSource → au moins un onglet ; sinon présence de la dataclass.
    grids = getattr(src, "grids", None)
    if grids is not None:
        return any(getattr(g, "rows", None) for g in grids)
    table = getattr(src, "table", None)
    if table is not None:
        return bool(getattr(table, "rows", None))
    return True


def _satisfied(
    req: DataRequirement,
    snap: ModelSnapshot | None,
    source_present: bool,
    has_audit: bool,
) -> bool:
    # Une source XLS MOA chargée pour ce rapport **porte toutes ses colonnes**
    # (métier ET Solibri) : le pack sait la reproduire → toute donnée requise est
    # satisfaite. (Corrige le faux « blocked » en source-only.)
    if source_present:
        return True
    if req.kind == "external_source":
        return False
    if req.kind == "audit_or_control_source":
        # Source gérée ci-dessus ; reste l'AuditResult pour remplir la grille.
        return has_audit
    if snap is None:
        return False
    if req.kind == "ifc_entity":
        return _has_ifc_entity(snap, req.ifc_classes)
    if req.kind == "base_quantity":
        return _has_base_quantity(snap, req.ifc_classes, req.quantity or "")
    if req.kind == "relation_zone_space":
        return _has_zone_space_relation(snap)
    if req.kind == "envelope_layer":
        return count_envelope_walls(snap) > 0
    return False


def _next_action(status: str, missing_core: list[str], missing_external: list[str]) -> str:
    if status == "ready":
        return "Prêt : toutes les données requises sont disponibles."
    if status == "blocked":
        if missing_core:
            return (
                "Données maquette manquantes : "
                + ", ".join(missing_core)
                + ". Extraire un snapshot complet (status C) ou compléter la maquette."
            )
        return (
            "Reproduction à l'identique requise mais données externes absentes : "
            + ", ".join(missing_external)
            + ". Fournir l'export Solibri / la source MOA."
        )
    # partial
    return (
        "Rapport métier générable depuis la maquette. Pour la reproduction à "
        "l'identique, fournir : " + ", ".join(missing_external) + " (export Solibri / source MOA)."
    )


def _availability_for_spec(
    spec: ReportSpec,
    snap: ModelSnapshot | None,
    sources,
    require_identical: bool,
    has_audit: bool,
) -> ReportAvailability:
    source_present = _source_present(sources, spec.deliverable_key)

    available: list[str] = []
    missing: list[str] = []
    missing_core: list[str] = []
    missing_external: list[str] = []
    core_ok = True
    identical_ok = True

    for req in spec.requirements:
        ok = _satisfied(req, snap, source_present, has_audit)
        if ok:
            available.append(req.label)
        else:
            missing.append(req.label)
            identical_ok = False
            if req.identical_only:
                missing_external.append(req.label)
            else:
                core_ok = False
                missing_core.append(req.label)

    can_generate = core_ok
    can_generate_identical = identical_ok

    if not can_generate:
        status = "blocked"
    elif can_generate_identical:
        status = "ready"
    else:
        status = "partial"
    # Listing strict : un rapport « partial » ne satisfait pas l'exigence
    # « à l'identique » → il n'est pas prêt.
    if require_identical and not can_generate_identical:
        status = "blocked"

    return ReportAvailability(
        key=spec.key,
        label=spec.label,
        can_generate=can_generate,
        can_generate_identical=can_generate_identical,
        status=status,
        available_data=available,
        missing_data=missing,
        template_path=spec.resolved_template_path(),
        source_xlsx_required_for_identical=spec.requires_external_for_identical,
        next_action=_next_action(status, missing_core, missing_external),
    )


def inspect_avp_report_availability(
    snapshot: ModelSnapshot | None,
    sources=None,
    require_identical: bool = False,
    has_audit_result: bool = False,
) -> list[ReportAvailability]:
    """Verdict de disponibilité de **tous** les rapports du catalogue.

    Args:
        snapshot: snapshot BIMData courant (``None`` → tout rapport « blocked »).
        sources: ``AvpSources`` déjà chargées. Une source XLS chargée pour un
            rapport **porte toutes ses colonnes** (métier ET Solibri) → le
            rapport est reproductible depuis la source. ``None`` → aucune source.
        require_identical: si ``True``, un rapport n'est ``ready`` que si la
            reproduction stricte est possible (toutes colonnes MOA).
        has_audit_result: un ``AuditResult`` est disponible dans la session
            (audit lancé). Nécessaire pour remplir la **grille de contrôle** du
            rapport ``controle_maquettes`` quand aucune source Contrôle n'est
            fournie — le seul snapshot ne suffit pas.

    Returns:
        Liste ordonnée (ordre catalogue CTO) de :class:`ReportAvailability`.
    """
    return [
        _availability_for_spec(spec, snapshot, sources, require_identical, has_audit_result)
        for spec in REPORT_SPECS
    ]
