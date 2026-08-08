"""La trace de contrat dit ce qui a été utilisé — sans se mêler de l'autoriser.

``AvpContractTrace`` porte ce qu'il faut **dire** d'un contrat dans la réponse
du pack. ``_resolve_contract_source`` décide s'il est **acceptable**. Les deux
ne s'exécutent pas au même moment : ``coverage`` n'existe qu'après la fusion des
quantités dans le snapshot, bien après la résolution du chemin. Les mélanger
ferait porter au garde de provenance des champs qui n'existent pas encore
quand il agit.

Ces tests fixent deux choses : les **clés publiques** de la réponse, qui sont un
contrat d'API vis-à-vis du harnais, et le fait que les cinq origines réelles
(enveloppe explicite / détectée / calculée, quantités explicites / calculées)
produisent bien une trace.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from audit_bim.profiles.i3f.tools_reporting import AvpContractTrace

MODULE = Path(__file__).resolve().parents[2] / "audit_bim/profiles/i3f/tools_reporting.py"

#: Clés publiques de la réponse de succès. Elles sont lues par le harnais MCP :
#: en renommer une est un changement d'API, pas un détail de refactor.
CLES_PUBLIQUES = {
    "output_dir",
    "paths",
    "analyse_docx",
    "analyse_pdf",
    "pdf_available",
    "project_name",
    "project_code",
    "phase",
    "controle_xlsx_used",
    "envelope_json_used",
    "computed_quantities_json_used",
    "computed_quantities_coverage",
    "active_cloud_id",
    "active_project_id",
    "active_model_id",
    "downloaded_ifc_path",
    "computed_source_ifc_file",
    "envelope_source_ifc_file",
    "auto_computed",
}


def _cles_du_formatter() -> set[str]:
    fn = next(
        n
        for n in ast.walk(ast.parse(MODULE.read_text(encoding="utf-8")))
        if isinstance(n, ast.FunctionDef) and n.name == "_format_avp_pack_response"
    )
    ret = next(x for x in ast.walk(fn) if isinstance(x, ast.Return))
    return {k.value for k in ret.value.keys if isinstance(k, ast.Constant)}


def test_the_public_response_keys_are_unchanged():
    """Le refactor déplace des paramètres, jamais des clés de réponse."""
    assert _cles_du_formatter() == CLES_PUBLIQUES


def test_the_formatter_takes_traces_not_flat_fields():
    """Non-vacuité : les sept champs plats ne doivent plus être des paramètres."""
    fn = next(
        n
        for n in ast.walk(ast.parse(MODULE.read_text(encoding="utf-8")))
        if isinstance(n, ast.FunctionDef) and n.name == "_format_avp_pack_response"
    )
    params = {a.arg for a in fn.args.args} | {a.arg for a in fn.args.kwonlyargs}

    assert {"envelope_trace", "computed_trace"} <= params
    disparus = {
        "envelope_json_used",
        "envelope_source_ifc_file",
        "auto_envelope",
        "computed_json_used",
        "computed_source_ifc_file",
        "computed_coverage",
        "auto_quantities",
    }
    assert not (disparus & params), sorted(disparus & params)


@pytest.mark.parametrize(
    ("origine", "trace"),
    [
        # Enveloppe — trois origines, jamais de coverage.
        ("enveloppe explicite", AvpContractTrace(json_used="/in/e.json", source_ifc_file="M.ifc")),
        (
            "enveloppe détectée",
            AvpContractTrace(json_used="/in/auto_e.json", source_ifc_file="M.ifc"),
        ),
        (
            "enveloppe calculée",
            AvpContractTrace(
                json_used="/out/e.json",
                source_ifc_file="M.ifc",
                auto_result={"json_path": "/out/e.json"},
            ),
        ),
        # Quantités — deux origines, coverage seulement après fusion.
        (
            "quantités explicites",
            AvpContractTrace(
                json_used="/in/q.json", source_ifc_file="M.ifc", coverage={"slabs": 12}
            ),
        ),
        (
            "quantités calculées",
            AvpContractTrace(
                json_used="/out/q.json",
                source_ifc_file="M.ifc",
                auto_result={"json_path": "/out/q.json"},
                coverage={"slabs": 12},
            ),
        ),
    ],
)
def test_every_real_origin_produces_a_usable_trace(origine, trace):
    """Les cinq origines réelles se décrivent avec un seul type."""
    assert trace.json_used
    assert trace.source_ifc_file == "M.ifc"


def test_the_envelope_trace_carries_no_coverage_by_default():
    """L'asymétrie est portée par un défaut, pas par deux types.

    L'enveloppe ne produit pas de couverture ; les quantités si. Un second type
    pour cette seule différence aurait dupliqué trois champs sur quatre.
    """
    assert AvpContractTrace().coverage is None
    assert AvpContractTrace(coverage={"slabs": 1}).coverage == {"slabs": 1}


def test_an_absent_contract_is_an_empty_trace_not_a_missing_one():
    """Aucun contrat ⇒ une trace vide, pas un `None` à tester partout.

    Sans ça, le formatter devrait porter des gardes `if trace is not None` sur
    chacun des cinq champs qu'il expose.
    """
    vide = AvpContractTrace()
    assert (vide.json_used, vide.source_ifc_file, vide.auto_result, vide.coverage) == (
        None,
        None,
        None,
        None,
    )
