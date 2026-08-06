"""Outil MCP — couverture du référentiel MRN sur la maquette active.

Cet outil dit **ce qui est évaluable**, jamais **ce qui est conforme**. La
distinction n'est pas une prudence de langage. Sur MN_BAT, **877 des 1 013
exigences ne sont pas évaluables** — dont 680 parce que la classe IFC visée est
absente, et 197 parce que le Pset exigé ne correspond à aucun de la maquette.
C'est le total, 877, que renvoie ``false_non_conformity_risk`` : le nombre de
faux constats qu'aurait produits un outil concluant « non conforme » sur tout ce
qu'il ne peut pas évaluer. Personne ne relirait 877 lignes.

Le porteur actif est **déclaré par l'appelant**, jamais déduit du nom de la
maquette. Un nom de fichier n'est pas une donnée : deviner « ARC » parce que le
fichier s'appelle ``…_ARC.ifc`` reviendrait à fonder un verdict de périmètre sur
une convention de nommage que rien ne garantit.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ...mcp.app import mcp
from ...mcp.session import _State
from ...safe_paths import safe_export_path, safe_input_path
from .mrn import parse_mrn_attribute_table
from .mrn.coverage import assess_mrn_coverage

__all__ = ["analyze_mrn_model_coverage"]


@mcp.tool()
def analyze_mrn_model_coverage(
    attribute_table_xlsx: str,
    active_carriers: list[str] | None = None,
    export_path: str | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Mesure la couverture du référentiel MRN sur la maquette BIMData active.

    Répond à « combien des 1 013 exigences MRN peut-on évaluer sur cette
    maquette, et pourquoi pas les autres ». **Ne produit aucun statut de
    conformité** et n'écrit jamais dans la grille de contrôle du client.

    Args:
        attribute_table_xlsx: chemin de la table des attributs MRN.
        active_carriers: maquettes portées par le modèle analysé — ``["ARC"]``,
            ``["CVC"]``… **À déclarer explicitement.** Omis, aucune exigence ne
            peut être dite hors périmètre : sans savoir ce que porte ce modèle,
            l'affirmer serait une supposition. Le porteur n'est jamais déduit du
            nom de la maquette.
        export_path: si fourni, écrit la synthèse JSON sous la racine d'export.
        overwrite: autorise l'écrasement de cet export.

    Returns:
        Le résumé de couverture, dont ``false_non_conformity_risk`` : le nombre
        de faux constats qu'aurait produits un moteur concluant « non conforme »
        sur tout ce qu'il ne peut pas évaluer. C'est ce chiffre qui justifie de
        ne pas livrer de grille tant qu'il reste élevé.
    """
    try:
        if _State.client is None:
            raise RuntimeError("Aucune maquette active — appeler d'abord `set_active_target`.")

        table = parse_mrn_attribute_table(safe_input_path(attribute_table_xlsx))
        from ...extraction.model_data import extract_snapshot

        snapshot = _State.snapshot or extract_snapshot(_State.client)
        _State.snapshot = snapshot
        model_name = (snapshot.model or {}).get("name") or ""

        coverage = assess_mrn_coverage(
            table.requirements,
            snapshot,
            model_name=model_name,
            active_carriers=active_carriers,
        )
        summary = coverage.summary()

        not_evaluable = summary["requirements_total"] - summary["requirements_evaluable"]
        summary["false_non_conformity_risk"] = not_evaluable
        summary["active_carriers"] = list(active_carriers or [])
        summary["carrier_scope_known"] = bool(active_carriers)
        summary["conformity_statuses_emitted"] = []

        if export_path:
            target = safe_export_path(Path(export_path), overwrite=overwrite)
            target.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
            summary["export_path"] = str(target)

        return {"status": "ok", **summary}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": str(exc), "error_type": type(exc).__name__}
