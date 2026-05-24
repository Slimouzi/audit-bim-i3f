"""Enrichissement IFC depuis les Match DOE.

Pour chaque ``Match.is_matched()``, on regroupe les propriétés par Pset
et on crée le Pset complet en une requête HTTP sur l'élément IFC :

    POST /cloud/{}/project/{}/model/{}/element/{element_uuid}/propertyset

Avant écriture, on **classifie les conflits** (existant vs DOE) et on
applique la stratégie ``on_conflict`` choisie par l'utilisateur (cf.
:mod:`audit_bim.doe.conflicts`). Mode par défaut ``"report"`` : on
n'écrase **jamais** silencieusement une valeur existante différente.

Mode ``dry_run`` (défaut) : on calcule juste les payloads, on ne POST rien.
"""

from __future__ import annotations

from collections.abc import Iterable

from ..extraction.client import BIMDataClient
from ..extraction.model_data import ModelSnapshot
from .conflicts import (
    ConflictReport,
    ConflictType,
    detect_conflicts,
    summarize_conflicts,
)
from .models import Match


def _infer_value_type(value) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "float"
    return "string"


def _build_pset_payload(pset_name: str, props: dict) -> dict:
    return {
        "name": pset_name,
        "description": "Enrichissement automatique depuis DOE (agent audit-bim-i3f)",
        "properties": [
            {
                "definition": {
                    "name": str(prop_name),
                    "value_type": _infer_value_type(value),
                    "type": "IfcPropertySingleValue",
                },
                "value": value,
            }
            for prop_name, value in props.items()
        ],
    }


def _filter_props_by_conflict(
    pset_name: str,
    props: dict,
    reports: list[ConflictReport],
    *,
    on_conflict: str,
) -> tuple[dict, list[str]]:
    """Filtre les propriétés à écrire selon la stratégie de conflit.

    Args:
        pset_name: Nom du Pset auquel s'appliquent ``props``.
        props: Mapping ``{prop_name: doe_value}``.
        reports: Liste des ConflictReport pré-calculée par
            ``detect_conflicts`` pour le match courant.
        on_conflict: ``"report"`` / ``"skip"`` / ``"overwrite"``.

    Returns:
        Tuple ``(props_to_write, skipped_prop_names)`` :

        - ``props_to_write`` : sous-ensemble de ``props`` réellement à
          écrire (MATCH skippés systématiquement, CONFLICT skippés sauf
          en mode ``overwrite``).
        - ``skipped_prop_names`` : liste des propriétés non écrites
          (debug/reporting).
    """
    by_prop = {r.property: r for r in reports if r.pset == pset_name and r.property in props}
    to_write: dict = {}
    skipped: list[str] = []
    for prop_name, doe_value in props.items():
        rep = by_prop.get(prop_name)
        if rep is None:
            # Pas de report → on écrit (cas où aucune valeur existante n'a été
            # remontée, équivalent NEW).
            to_write[prop_name] = doe_value
            continue
        if rep.type == ConflictType.MATCH:
            # Pas la peine d'écrire la même valeur.
            skipped.append(prop_name)
            continue
        if rep.type == ConflictType.CONFLICT and on_conflict != "overwrite":
            # Mode report/skip → on n'écrase pas.
            skipped.append(prop_name)
            continue
        # NEW, UPGRADE, ou CONFLICT en overwrite → on écrit.
        to_write[prop_name] = doe_value
    return to_write, skipped


def apply_matches_to_model(
    client: BIMDataClient,
    matches: Iterable[Match],
    *,
    dry_run: bool = True,
    snapshot: ModelSnapshot | None = None,
    on_conflict: str = "report",
) -> dict:
    """Pousse les Psets DOE sur les éléments IFC matchés, avec gestion des conflits.

    Étapes :

    1. Calcule les conflits existant ↔ DOE via ``detect_conflicts`` si
       ``snapshot`` est fourni (sinon mode V1 — écriture tout).
    2. Pour chaque (match, pset), filtre les propriétés à écrire via
       ``_filter_props_by_conflict`` selon ``on_conflict``.
    3. POST le Pset filtré si non vide.

    Args:
        client: Client BIMData authentifié.
        matches: Itérable de Match. Les non-matchés sont ignorés.
        dry_run: ``True`` (défaut) = pas d'appel POST.
        snapshot: ModelSnapshot pour détection des conflits. **Très
            recommandé** ; absence = mode legacy V1 (écrit sans vérifier).
        on_conflict: Stratégie de résolution des CONFLICT :

            - ``"report"`` (défaut) : signale dans le rapport, n'écrase
              **pas** les valeurs existantes différentes.
            - ``"skip"`` : comme report mais sans détail nominal.
            - ``"overwrite"`` : écrit toutes les valeurs DOE, y compris
              celles en conflit. À utiliser si DOE est autoritaire.

    Returns:
        Dict avec :

        - ``dry_run``, ``n_matched``
        - ``n_psets_planned`` / ``n_psets_pushed``
        - ``n_properties_planned`` (= NEW + UPGRADE + CONFLICT-en-overwrite)
        - ``n_properties_skipped`` (= MATCH + CONFLICT-en-report/skip)
        - ``conflicts_summary`` : compteurs par type
        - ``conflicts`` : liste des ConflictReport si ``on_conflict ==
          "report"``, vide sinon
        - ``errors`` : erreurs HTTP collectées
        - ``preview`` : 50 premiers Psets à pousser (debug)
    """
    matched = [m for m in matches if m.is_matched()]
    if not matched:
        return {
            "dry_run": dry_run,
            "on_conflict": on_conflict,
            "n_matched": 0,
            "n_psets_planned": 0,
            "message": "Aucun élément matché — rien à appliquer.",
        }

    # 1. Détection des conflits (si snapshot fourni)
    conflict_reports: list[ConflictReport] = (
        detect_conflicts(matched, snapshot) if snapshot is not None else []
    )
    reports_by_uuid: dict[str, list[ConflictReport]] = {}
    for r in conflict_reports:
        reports_by_uuid.setdefault(r.element_uuid, []).append(r)

    n_psets = 0
    n_props = 0
    n_skipped = 0
    n_pushed = 0
    errors: list[str] = []
    preview: list[dict] = []

    base = f"/cloud/{client.cloud_id}/project/{client.project_id}/model/{client.model_id}/element"

    for m in matched:
        match_reports = reports_by_uuid.get(m.ifc_uuid or "", [])
        for pset_name, props in (m.record.properties or {}).items():
            if not props:
                continue
            # Filtrage selon les conflits (no-op si conflict_reports vide)
            if conflict_reports:
                props_to_write, skipped_names = _filter_props_by_conflict(
                    pset_name, props, match_reports, on_conflict=on_conflict
                )
            else:
                props_to_write, skipped_names = dict(props), []

            n_skipped += len(skipped_names)
            if not props_to_write:
                continue

            payload = _build_pset_payload(pset_name, props_to_write)
            preview.append(
                {
                    "element_uuid": m.ifc_uuid,
                    "ifc_type": m.ifc_type,
                    "ifc_name": m.ifc_name,
                    "confidence": m.confidence,
                    "strategy": m.strategy,
                    "pset": pset_name,
                    "n_properties": len(props_to_write),
                    "skipped_properties": skipped_names,
                }
            )
            n_psets += 1
            n_props += len(props_to_write)
            if dry_run:
                continue
            try:
                client._post(f"{base}/{m.ifc_uuid}/propertyset", payload)
                n_pushed += 1
            except Exception as e:
                errors.append(f"element {m.ifc_uuid} pset {pset_name}: {e}")

    # Rapport conflits — détaillé si 'report', juste compteurs sinon
    conflicts_detail = (
        [r.model_dump(mode="json") for r in conflict_reports if r.type == ConflictType.CONFLICT]
        if on_conflict == "report"
        else []
    )

    return {
        "dry_run": dry_run,
        "on_conflict": on_conflict,
        "n_matched": len(matched),
        "n_psets_planned": n_psets,
        "n_psets_pushed": n_pushed,
        "n_properties_planned": n_props,
        "n_properties_skipped": n_skipped,
        "conflicts_summary": summarize_conflicts(conflict_reports),
        "conflicts": conflicts_detail[:50],  # cap MCP
        "errors": errors,
        "preview": preview[:50],
    }
