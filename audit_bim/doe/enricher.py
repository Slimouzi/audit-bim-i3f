"""Enrichissement IFC depuis les Match DOE.

Pour chaque ``Match.is_matched()``, on regroupe les propriétés par Pset et
on crée le Pset complet en une requête sur l'élément IFC dans BIMData.

API utilisée :
``POST /cloud/{}/project/{}/model/{}/element/{element_uuid}/propertyset``
Body : ``PropertySetRequest`` avec ``name`` + ``properties[*]{definition,value}``.

Mode ``dry_run`` (défaut) : on calcule juste les payloads, on ne POST rien.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from ..extraction.client import BIMDataClient
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


def apply_matches_to_model(
    client: BIMDataClient,
    matches: Iterable[Match],
    *,
    dry_run: bool = True,
) -> dict:
    """Pousse les Psets DOE sur les éléments IFC matchés dans BIMData.

    Pour chaque ``Match.is_matched()``, regroupe ses propriétés par Pset
    et crée le Pset complet en une requête HTTP via :

        POST /cloud/{}/project/{}/model/{}/element/{uuid}/propertyset

    Le ``value_type`` IFC est inféré du type Python de la valeur
    (boolean / integer / float / string).

    En ``dry_run`` (défaut), aucun POST n'est émis — la fonction renvoie
    juste les compteurs et un échantillon de preview, pour permettre à
    l'utilisateur de valider avant écriture irréversible.

    Args:
        client: Client BIMData authentifié.
        matches: Itérable de Match. Les non-matchés sont ignorés.
        dry_run: True (défaut) = pas d'appel POST.

    Returns:
        Dict ``{dry_run, n_matched, n_psets_planned, n_psets_pushed,
        n_properties_planned, errors, preview}``. ``preview`` est cappé
        à 50 entrées pour préserver le canal MCP.
    """
    matched = [m for m in matches if m.is_matched()]
    if not matched:
        return {
            "dry_run": dry_run,
            "n_matched": 0,
            "n_psets_planned": 0,
            "message": "Aucun élément matché — rien à appliquer.",
        }

    n_psets = 0
    n_props = 0
    n_pushed = 0
    errors: list[str] = []
    preview: list[dict] = []

    base = (
        f"/cloud/{client.cloud_id}/project/{client.project_id}"
        f"/model/{client.model_id}/element"
    )

    for m in matched:
        for pset_name, props in (m.record.properties or {}).items():
            if not props:
                continue
            payload = _build_pset_payload(pset_name, props)
            preview.append(
                {
                    "element_uuid": m.ifc_uuid,
                    "ifc_type": m.ifc_type,
                    "ifc_name": m.ifc_name,
                    "confidence": m.confidence,
                    "strategy": m.strategy,
                    "pset": pset_name,
                    "n_properties": len(props),
                }
            )
            n_psets += 1
            n_props += len(props)
            if dry_run:
                continue
            try:
                client._post(f"{base}/{m.ifc_uuid}/propertyset", payload)
                n_pushed += 1
            except Exception as e:
                errors.append(
                    f"element {m.ifc_uuid} pset {pset_name}: {e}"
                )

    return {
        "dry_run": dry_run,
        "n_matched": len(matched),
        "n_psets_planned": n_psets,
        "n_psets_pushed": n_pushed,
        "n_properties_planned": n_props,
        "errors": errors,
        "preview": preview[:50],  # cap pour préserver le canal MCP
    }
