"""Garde-fou : les tools MCP `prepare_*` (et leurs alias métier) doivent
accepter les filtres passés en JSON string dans leur schéma.

Certains clients MCP sérialisent les paramètres objets en JSON string ; si
l'annotation n'inclut pas ``str``, le schéma advertise ``object|null`` et le
paramètre est rejeté *avant* d'entrer dans le tool (où ``_coerce_json_dict``
le récupérerait). Ce test empêche l'alias de dériver de sa fonction cible.
"""

from __future__ import annotations

import inspect

import pytest

import audit_bim.mcp.aliases as al
import audit_bim.mcp.tools_actions as ta

# (module, nom du tool, paramètre de filtre)
_FILTER_TOOLS = [
    (ta, "prepare_bcf_topics", "finding_filter"),
    (ta, "prepare_smart_views_plan", "finding_filter"),
    (ta, "prepare_classification_update_plan", "suggestion_filter"),
    (al, "prepare_bcf_from_findings", "finding_filter"),
    (al, "prepare_smartviews_from_findings", "finding_filter"),
    (al, "prepare_classification_corrections", "suggestion_filter"),
]


def _underlying(tool):
    """Fonction sous-jacente d'un tool FastMCP (exposée via ``.fn``)."""
    return getattr(tool, "fn", getattr(tool, "__wrapped__", tool))


@pytest.mark.parametrize("module, name, param", _FILTER_TOOLS)
def test_filter_param_accepts_json_string(module, name, param):
    fn = _underlying(getattr(module, name))
    annotation = inspect.signature(fn).parameters[param].annotation
    assert "str" in str(annotation), (
        f"{name}.{param} n'accepte pas les filtres JSON string "
        f"(annotation={annotation!r}) — le schéma MCP les rejettera."
    )
