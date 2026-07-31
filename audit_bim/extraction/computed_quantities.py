"""Fusion des BaseQuantities **calculées** (MCP ifc-geometry) dans le snapshot.

Consomme le contrat JSON ``computed_base_quantities/v1`` produit par
``export_computed_base_quantities`` (MCP ifc-geometry) et fusionne les valeurs
dans le snapshot BIMData courant, en **gap-only** :

- **jointure** par ``BimObject.uuid == global_id`` (GlobalId IFC) ;
- **jamais d'écrasement** : une BaseQuantity déjà présente (native BIMData) est
  conservée telle quelle ; on ne comble que les vides ;
- entrées ``status != "computed"`` (skipped / failed) **ignorées** ;
- ``global_id`` inconnu du snapshot → **ignoré avec warning** ;
- **provenance par valeur** conservée sur l'élément (``computed_base_quantities``)
  : ``source="computed_ifcopenshell"``, ``method``, ``unit``, ``status``.

La valeur calculée est injectée dans les ``property_sets`` de l'élément (pset
``Qto_*BaseQuantities``) → lue **à l'identique** par les builders AVP
(``_base_quantity_ordered``) et par ``bim_object_from_element``
(``_extract_base_quantities``), sans distinction de source côté lecture.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

EXPORT_SCHEMA = "computed_base_quantities/v1"
SOURCE_COMPUTED = "computed_ifcopenshell"

# Préfixes de pset reconnus comme BaseQuantities (aligné bim_query / avp).
_BQ_PREFIXES = ("basequantities", "qto_", "quantit")


def load_computed_quantities(json_path: str | Path) -> dict[str, Any]:
    """Charge et **valide** le JSON ``computed_base_quantities/v1``.

    Raises:
        ValueError: fichier absent, illisible, ou schéma inattendu.
    """
    p = Path(json_path)
    if not p.is_file():
        raise ValueError(f"JSON de quantités calculées introuvable : {json_path}")
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"JSON de quantités calculées illisible : {exc}") from exc
    if not isinstance(doc, dict) or doc.get("schema") != EXPORT_SCHEMA:
        raise ValueError(
            f"Schéma inattendu : {doc.get('schema') if isinstance(doc, dict) else type(doc).__name__!r} "
            f"(attendu {EXPORT_SCHEMA!r})."
        )
    if not isinstance(doc.get("quantities"), list):
        raise ValueError("Champ `quantities` manquant ou invalide dans le JSON.")
    return doc


def json_digest(json_path: str | Path) -> str:
    """Empreinte courte (sha256 tronqué) du contenu du JSON — pour la clé de cache."""
    return hashlib.sha256(Path(json_path).read_bytes()).hexdigest()[:16]


def _has_quantity(element: dict, qty_name: str) -> bool:
    """Vrai si l'élément porte déjà cette BaseQuantity (valeur numérique)."""
    target = (qty_name or "").lower()
    for pset in element.get("property_sets") or []:
        pname = (pset.get("name") or "").lower()
        if not pname.startswith(_BQ_PREFIXES):
            continue
        for prop in pset.get("properties") or []:
            pn = ((prop.get("definition") or {}).get("name") or "").lower()
            val = prop.get("value")
            if pn == target and isinstance(val, (int, float)) and not isinstance(val, bool):
                return True
    return False


def _inject(element: dict, qto_name: str, qty_name: str, value: float) -> None:
    """Ajoute la quantité dans un pset BaseQuantities (du même ``qto_name`` si
    présent, sinon nouveau) — forme lue par les builders et bim_object."""
    psets = element.setdefault("property_sets", [])
    pset = next((p for p in psets if (p.get("name") or "") == qto_name), None)
    if pset is None:
        pset = {"name": qto_name, "properties": []}
        psets.append(pset)
    pset.setdefault("properties", []).append(
        {"definition": {"name": qty_name}, "value": float(value)}
    )


def merge_into_snapshot(snapshot, doc: dict[str, Any]) -> dict[str, Any]:
    """Fusionne (gap-only) les quantités calculées de ``doc`` dans ``snapshot``.

    Mute les éléments **indexés par uuid** (ceux que lisent ``_rich`` côté AVP et
    ``get_object_detail``). Renvoie une **couverture** sérialisable.
    """
    index = snapshot.element_by_uuid or {}
    n_merged = n_gap_kept = n_skipped_status = n_unknown = 0
    warnings: list[str] = []

    for q in doc.get("quantities") or []:
        if q.get("status") != "computed" or q.get("value") is None:
            n_skipped_status += 1
            continue
        gid = q.get("global_id")
        element = index.get(gid)
        if element is None:
            n_unknown += 1
            if len(warnings) < 50:
                warnings.append(f"global_id inconnu dans le snapshot, ignoré : {gid}")
            continue
        qty = q.get("quantity")
        qto = q.get("qto") or "Qto_BaseQuantities"
        if _has_quantity(element, qty):
            n_gap_kept += 1  # valeur BIMData existante → jamais écrasée
            continue
        _inject(element, qto, qty, q["value"])
        prov = element.setdefault("computed_base_quantities", [])
        prov.append(
            {
                "quantity": qty,
                "qto": qto,
                "value": float(q["value"]),
                "unit": q.get("unit"),
                "method": q.get("method"),
                "status": q.get("status"),
                "source": q.get("source") or SOURCE_COMPUTED,
            }
        )
        n_merged += 1

    return {
        "n_merged": n_merged,
        "n_gap_kept": n_gap_kept,
        "n_skipped_status": n_skipped_status,
        "n_unknown_uuid": n_unknown,
        "warnings": warnings,
    }
