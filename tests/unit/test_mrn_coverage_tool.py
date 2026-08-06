"""Outil MCP de couverture MRN — il mesure, il ne juge pas.

Ce fichier protège une frontière plutôt qu'un comportement : l'outil ne doit
jamais émettre de statut de conformité, ni écrire dans la grille du client.
"""

from __future__ import annotations

import ast
from pathlib import Path

# Lu par chemin, sans importer le module : l'importer déclencherait son
# ``@mcp.tool`` sur l'instance partagée du processus de test, et tous les
# fichiers exécutés ensuite mesureraient une surface I3F gonflée d'un outil.
REPO = Path(__file__).resolve().parents[2]
TOOL_MODULE = REPO / "audit_bim" / "profiles" / "bim_in_motion" / "tools_mrn.py"
SOURCE = TOOL_MODULE.read_text(encoding="utf-8")


def test_the_tool_is_declared_by_the_third_party_profile():
    from audit_bim.profiles.registry import get_profile

    modules = get_profile("bim_in_motion").tool_modules
    assert "audit_bim.profiles.bim_in_motion.tools_mrn" in modules


def test_no_conformity_verdict_can_be_emitted():
    """Aucun libellé de conformité ne doit exister dans ce module.

    Sur une maquette architecturale, 877 exigences ne sont pas évaluables. Un
    outil qui rendrait « non conforme » produirait un livrable chiffré,
    crédible et faux — et personne ne relirait les 877 lignes.
    """
    forbidden = ("Conforme", "Non conforme", "Partiellement conforme")
    tree = ast.parse(SOURCE)
    literals = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]
    docstring = ast.get_docstring(tree, clean=False) or ""
    shipped = [text for text in literals if text != docstring]

    assert not [t for t in shipped for f in forbidden if f in t]


def test_the_tool_never_writes_into_the_client_grid():
    """Le gabarit de contrôle n'est ni ouvert ni écrit par ce lot."""
    assert "GRILLE_CONTROLE" not in SOURCE.upper()
    assert "openpyxl" not in SOURCE
    assert "parse_mrn_template" not in SOURCE
    assert "control_template" not in SOURCE


def test_the_active_carrier_is_never_inferred():
    """Un nom de fichier n'est pas une donnée.

    Deviner « ARC » parce que la maquette s'appelle ``…_ARC.ifc`` fonderait un
    verdict de périmètre sur une convention de nommage que rien ne garantit.
    """
    tree = ast.parse(SOURCE)
    function = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "analyze_mrn_model_coverage"
    )
    args = [a.arg for a in function.args.args] + [a.arg for a in function.args.kwonlyargs]
    assert "active_carriers" in args

    body = ast.get_source_segment(SOURCE, function) or ""
    for guess in ("model_name.upper()", "in model_name", "startswith(", "_ARC"):
        assert guess not in body, f"le porteur ne doit pas se déduire ({guess})"


def test_a_missing_target_is_refused_by_name():
    """Le message doit nommer un outil de ce profil, pas d'un autre.

    Exécuté en sous-processus : importer le module ici enregistrerait l'outil
    sur l'instance MCP partagée et fausserait la surface mesurée ailleurs.
    """
    import json
    import subprocess
    import sys

    probe = (
        "import json\n"
        "from audit_bim.profiles.bim_in_motion.tools_mrn import analyze_mrn_model_coverage\n"
        "print(json.dumps(analyze_mrn_model_coverage('/inexistant.xlsx')))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        cwd=REPO,
        env={"PATH": "/usr/bin:/bin", "HOME": str(REPO), "AUDIT_BIM_PROFILE": "bim_in_motion"},
        timeout=180,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    payload = json.loads(result.stdout.strip().splitlines()[-1])

    assert payload["status"] == "error"
    assert "set_active_target" in payload["error"] or "introuvable" in payload["error"]


def test_the_contract_keys_come_from_the_real_payload():
    """Le contrat se vérifie sur la sortie, pas sur le texte du module.

    Une première version cherchait les clés dans le source — elles viennent de
    ``summary()``, donc le test ne mesurait que ma façon de nommer des
    variables.
    """
    from dataclasses import dataclass, field

    from audit_bim.profiles.bim_in_motion.mrn.coverage import assess_mrn_coverage

    @dataclass
    class _Req:
        sheet: str = "Généralités"
        row: int = 4
        property_name: str = "Name"
        ifc_object: str = "IfcWall"
        pset: str = ""
        carrier_models: list = field(default_factory=list)

    class _Snap:
        elements = [{"type": "IfcWall", "property_sets": []}]

    summary = assess_mrn_coverage([_Req()], _Snap(), model_name="M").summary()
    for key in (
        "requirements_total",
        "requirements_evaluable",
        "evaluability_rate",
        "by_status",
        "per_sheet",
        "verdict",
    ):
        assert key in summary, key

    # Les clés que l'outil ajoute par-dessus la synthèse.
    for key in ("false_non_conformity_risk", "active_carriers", "carrier_scope_known"):
        assert key in SOURCE, key


def test_the_false_non_conformity_risk_is_what_justifies_the_scope():
    """Ce chiffre est la raison de ne pas livrer de grille.

    Il compte les exigences qu'un moteur naïf aurait déclarées non conformes
    faute de pouvoir les évaluer.
    """
    assert "false_non_conformity_risk" in SOURCE
    assert "requirements_total" in SOURCE and "requirements_evaluable" in SOURCE
