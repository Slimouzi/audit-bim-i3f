"""Outil MCP — ce que la maquette permet de trancher du référentiel client.

Cet outil dit **ce qui est évaluable**, jamais **ce qui est conforme**. Il
n'écrit ni dans le classeur du maître d'ouvrage, ni dans aucun tableur : la
seule sortie facultative est un résumé JSON.

Deux portes, et la seconde est le point de l'outil. Une famille de contrôles
doit être **revendiquée par une règle du registre**, qui nomme le champ qu'elle
lirait ; et ce champ doit être **effectivement renseigné** dans le document de
preuves fourni. Sans la seconde, on retomberait sur un classement par mots-clés
— lequel sature à 80 % en s'appuyant sur « présence » et « accès », deux mots
qui traversent presque tout un référentiel sans rien rendre mesurable.

Une troisième condition existe, moins visible : un champ rempli n'est pas
nécessairement la bonne preuve. Une famille peut rester revendiquée pour la
traçabilité tout en étant déclarée insuffisante — sans quoi son manque
disparaîtrait dans la relecture manuelle.

Le document de preuves est fourni par l'appelant. Ce profil ne le fabrique pas :
il vit dans un serveur géométrique distinct, et le confondre avec un calcul
local ferait croire que la mesure vient d'ici.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from ...mcp.app import mcp
from ...safe_paths import safe_export_path, safe_input_path
from .controls import parse_controls
from .coverage import STATUSES, assess, metric_core, read_evidence

__all__ = ["analyze_domofrance_model_coverage"]


@mcp.tool()
def analyze_domofrance_model_coverage(
    controls_xlsx: str,
    spatial_evidence_json: str,
    export_path: str | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Mesure ce qui est évaluable, en croisant référentiel client et preuves.

    Répond à « avec cette maquette et ce référentiel, que peut-on trancher, et
    pourquoi pas le reste ». **N'émet aucun statut de conformité** et n'écrit
    jamais dans le classeur du client.

    Args:
        controls_xlsx: chemin du classeur de contrôles du maître d'ouvrage.
        spatial_evidence_json: chemin d'un document de preuves géométriques
            ``spatial_evidence/v1``, produit en amont par le serveur
            géométrique. Un document invalide est refusé ; un document dont la
            provenance est ancienne ou inconnue est accepté avec avertissement.
        export_path: si fourni, écrit le résumé JSON sous la racine d'export.
        overwrite: autorise l'écrasement de cet export.

    Returns:
        Les compteurs d'évaluabilité, dont ``evaluable_in_metric_core`` — la
        base restreinte, celle qui se compare d'une mission à l'autre — et
        ``evaluable_total`` sur l'ensemble des contrôles distincts. Publier les
        deux est délibéré : n'en donner qu'un ferait passer un changement de
        base pour un gain de couverture. ``provenance_warnings`` porte les
        réserves sur l'origine des mesures, jamais un refus.
    """
    try:
        controls = parse_controls(safe_input_path(controls_xlsx))
        facts = read_evidence(str(safe_input_path(spatial_evidence_json)))
        assessments = [assess(control, facts) for control in controls]

        # Un contrôle écrit deux fois dans le classeur reste un contrôle : les
        # compteurs portent sur les identités, jamais sur les lignes.
        distinct = {a.control.identity: a for a in assessments}
        core = {c.identity for c in metric_core([a.control for a in distinct.values()])}
        par_statut = Counter(a.status for a in distinct.values())

        summary = {
            "controls_total": len(assessments),
            "logical_controls": len(distinct),
            "metric_core": len(core),
            "rules_claimed": len({a.rule for a in distinct.values() if a.rule}),
            "evaluable_in_metric_core": sum(
                1
                for a in distinct.values()
                if a.status == "evaluable_by_spatial_evidence" and a.control.identity in core
            ),
            "evaluable_total": par_statut["evaluable_by_spatial_evidence"],
            "by_status": {status: par_statut[status] for status in STATUSES},
            "evidence_schema": facts.schema,
            "evidence_producer": facts.provenance.producer if facts.provenance else None,
            "evidence_version": facts.source_version,
            "provenance_warnings": list(facts.warnings),
            "conformity_statuses_emitted": [],
        }

        if export_path:
            target = safe_export_path(Path(export_path), overwrite=overwrite)
            target.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
            summary["export_path"] = str(target)

        return {"status": "ok", **summary}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": str(exc), "error_type": type(exc).__name__}
