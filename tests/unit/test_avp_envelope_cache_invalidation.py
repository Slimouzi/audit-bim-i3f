"""Un contrat d'enveloppe en cache n'est réutilisable qu'aux **mêmes conditions**.

La corrélation au modèle ne suffit pas. Un ``envelope.json`` déjà présent porte
le résultat d'un calcul **passé** : motifs, mode et version du backend peuvent
différer de la demande courante, et rien dans les chiffres ne le signale — ce
sont des surfaces plausibles dans les deux cas.

Le risque est concret : le ratio FAC/SHAB a changé de **formule** en
ifc-geometry-mcp v0.4.0 et de **dénominateur** en v0.5.0. Un contrat 0.4.0
réutilisé produirait un livrable dont la note de méthode annonce une définition
que les chiffres ne suivent pas.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from audit_bim.extraction import geometry_backend
from audit_bim.extraction.model_data import ModelSnapshot
from audit_bim.mcp.session import _Session, current_session
from audit_bim.reporting import avp_autocompute
from audit_bim.reporting.avp_autocompute import CONTRACTS_SUBDIR, ensure_envelope_json

STEM = "DIEPPE-7427L"
TYPE_PATTERN = r"MUR ENDUIT|BARDAGE BOIS|ZINC|VERRE REGLIT"
MODE = "geometric_type_filter"
#: Version du backend simulée. Le job de tests CI n'installe pas l'extra
#: ``geometry`` : dépendre de la version réellement installée rendrait ces tests
#: verts en local et rouges en CI, pour une raison sans rapport avec ce qu'ils
#: vérifient.
VERSION_BACKEND = "0.5.0"


def _contrat(*, version=None, methode_shab="pieces_zonees_hors_annexes", seuil=None, **filtres):
    f = {
        "mode": MODE,
        "layer_pattern": None,
        "type_pattern": TYPE_PATTERN,
        "types_retenus": ["Mur de base:MUR ENDUIT 20 mm"],
        "types_rejetes": [],
    }
    f.update(filtres)
    summary = {
        "superficie_facades_m2": 2206.19,
        "superficie_facades_nette_m2": 2206.19,
        "superficie_menuiseries_m2": 375.89,
        "shab_m2": 2392.64,
        "ratio_fac_shab": 0.9221,
        "methode_facade": MODE,
    }
    if methode_shab is not None:
        summary["methode_shab"] = methode_shab
    if seuil is not None:
        summary["seuil_i3f"] = seuil
    return {
        "schema": "envelope_quantities/v1",
        "source": {
            "producer": "ifc-geometry",
            "tool": "extract_envelope_surfaces",
            "version": version if version is not None else VERSION_BACKEND,
            "ifc_file": f"{STEM}.ifc",
        },
        "created_at": "2026-08-03T08:00:00+00:00",
        "summary": summary,
        "par_type": [
            {
                "type": "Mur de base:MUR ENDUIT 20 mm",
                "etages": ["RDC"],
                "net_side_area_m2": 2206.19,
                "n": 54,
            }
        ],
        "hors_filtre_type": [],
        "diagnostics": {"filters": f},
    }


@pytest.fixture
def session(tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIT_OUTPUT_DIR", str(tmp_path))
    monkeypatch.setenv("AUDIT_INPUT_DIR", str(tmp_path))
    sess = _Session()
    sess.snapshot = ModelSnapshot(
        project={"name": "MCP_Audit"}, model={"name": f"{STEM}.ifc"}
    ).index()
    token = current_session.set(sess)
    try:
        yield sess, tmp_path
    finally:
        current_session.reset(token)


@pytest.fixture
def backend(monkeypatch):
    """Compte les calculs réels : c'est la seule preuve d'un recalcul."""
    appels = {"n": 0}

    def _fake(ifc_path, **kw):
        appels["n"] += 1
        return _contrat(
            mode=kw.get("filter_mode") or MODE,
            type_pattern=kw.get("type_pattern"),
            layer_pattern=kw.get("layer_pattern"),
            seuil=kw.get("seuil_3f"),
        )

    monkeypatch.setattr(avp_autocompute, "compute_envelope_payload", _fake)
    # ``backend_version`` est importée DANS la fonction : c'est le module source
    # qu'il faut substituer, pas une référence recopiée.
    monkeypatch.setattr(geometry_backend, "backend_version", lambda: VERSION_BACKEND)
    return appels


def _poser_cache(tmp_path, doc):
    dossier = tmp_path / CONTRACTS_SUBDIR
    dossier.mkdir(parents=True, exist_ok=True)
    (dossier / f"{STEM}_envelope.json").write_text(
        json.dumps(doc, ensure_ascii=False), encoding="utf-8"
    )


def _ifc(tmp_path):
    chemin = tmp_path / f"{STEM}.ifc"
    chemin.write_text("ISO-10303-21;", encoding="utf-8")
    return chemin


def _appel(tmp_path, sess, **kw):
    params = {
        "ifc_path": str(_ifc(tmp_path)),
        "type_pattern": TYPE_PATTERN,
        "filter_mode": MODE,
    }
    params.update(kw)
    return ensure_envelope_json(sess.snapshot, **params)


def test_a_0_4_0_contract_without_shab_method_is_recomputed(session, backend, tmp_path):
    """Le cas qui a motivé ce garde-fou.

    Un contrat produit avant v0.5.0 ne déclare pas la nature de son dénominateur.
    Le réutiliser livrerait un pack dont la note de méthode reste muette sur la
    SHAB — ou pire, un ratio calculé selon l'ancienne définition.
    """
    sess, _ = session
    _poser_cache(tmp_path, _contrat(version="0.4.0", methode_shab=None))

    res = _appel(tmp_path, sess)

    assert backend["n"] == 1, "le contrat sans methode_shab doit être recalculé"
    assert res["computed"] is True
    assert res["reused"] is False


def test_a_contract_from_another_backend_version_is_recomputed(session, backend, tmp_path):
    """Deux versions rendent le même schéma sous des définitions différentes."""
    sess, _ = session
    _poser_cache(tmp_path, _contrat(version="0.4.0"))

    _appel(tmp_path, sess)

    assert backend["n"] == 1


def test_a_contract_with_another_type_pattern_is_recomputed(session, backend, tmp_path):
    """Même modèle, autre motif : ce sont d'autres façades."""
    sess, _ = session
    _poser_cache(tmp_path, _contrat(type_pattern=r"BETON|MOB"))

    _appel(tmp_path, sess)

    assert backend["n"] == 1


def test_a_contract_with_another_mode_is_recomputed(session, backend, tmp_path):
    """Le mode change la nature de la sélection, donc du total."""
    sess, _ = session
    _poser_cache(tmp_path, _contrat(mode="geometric"))

    _appel(tmp_path, sess)

    assert backend["n"] == 1


def test_a_matching_contract_is_reused(session, backend, tmp_path):
    """Mêmes modèle, mêmes filtres, même version : pas de recalcul inutile.

    Sans ce cas, le garde-fou pourrait « passer » en recalculant toujours — ce
    qui masquerait une invalidation cassée derrière un comportement correct.
    """
    sess, _ = session
    _poser_cache(tmp_path, _contrat())

    res = _appel(tmp_path, sess)

    assert backend["n"] == 0
    assert res["reused"] is True
    assert res["computed"] is False


def test_force_recomputes_even_a_valid_cache(session, backend, tmp_path):
    """Rejeu explicite : maquette modifiée en place, recette à refaire."""
    sess, _ = session
    _poser_cache(tmp_path, _contrat())

    res = _appel(tmp_path, sess, force=True)

    assert backend["n"] == 1
    assert res["computed"] is True


def test_the_tool_exposes_force_recompute_envelope(session, backend, tmp_path, monkeypatch):
    """Le paramètre doit exister ET atteindre ``ensure_envelope_json``."""
    from audit_bim.mcp import server as mcp_server

    sess, _ = session
    sess.snapshot = ModelSnapshot(
        project={"name": "MCP_Audit"},
        model={"name": f"{STEM}.ifc"},
        elements=[{"uuid": "W1", "type": "IfcWall", "name": "Mur de base:MUR ENDUIT 20 mm"}],
    ).index()
    _poser_cache(tmp_path, _contrat())

    mcp_server.generate_avp_i3f_pack(
        project_name="Dieppe",
        project_code="7427L",
        phase="APD",
        auditor_name="Stanislas Limouzi",
        envelope_filter_mode=MODE,
        envelope_type_pattern=TYPE_PATTERN,
        force_recompute_envelope=True,
        auto_compute_quantities=False,
        ifc_path=str(_ifc(tmp_path)),
        export_pdf=False,
    )

    assert backend["n"] == 1, "force_recompute_envelope doit forcer le recalcul"


def test_the_recomputed_contract_is_written_where_it_is_read(session, backend, tmp_path):
    """Un recalcul qui n'écrase pas le cache le laisserait périmé."""
    sess, _ = session
    _poser_cache(tmp_path, _contrat(version="0.4.0", methode_shab=None))

    res = _appel(tmp_path, sess)

    ecrit = json.loads(Path(res["json_path"]).read_text(encoding="utf-8"))
    assert ecrit["summary"].get("methode_shab")
    assert ecrit["source"]["version"] == VERSION_BACKEND


# ── seuil 3F : il entre dans le contrat et dans l'annexe ───────────────


def test_a_contract_with_another_threshold_is_recomputed(session, backend, tmp_path):
    """Le seuil alimente ``conforme_seuil`` : deux seuils, deux verdicts."""
    sess, _ = session
    _poser_cache(tmp_path, _contrat(seuil=0.90))

    _appel(tmp_path, sess, seuil_3f=0.95)

    assert backend["n"] == 1


def test_a_contract_with_a_threshold_does_not_answer_a_request_without_one(
    session, backend, tmp_path
):
    """``None`` n'est pas « n'importe quelle valeur » : c'est « pas de seuil »."""
    sess, _ = session
    _poser_cache(tmp_path, _contrat(seuil=0.90))

    _appel(tmp_path, sess)  # aucune demande de seuil

    assert backend["n"] == 1


def test_a_request_with_a_threshold_is_not_served_by_a_contract_without_one(
    session, backend, tmp_path
):
    """Le cas symétrique, qui laisserait sinon l'annexe sans seuil affiché."""
    sess, _ = session
    _poser_cache(tmp_path, _contrat())  # pas de seuil_i3f

    _appel(tmp_path, sess, seuil_3f=0.90)

    assert backend["n"] == 1


def test_a_matching_threshold_is_reused(session, backend, tmp_path):
    sess, _ = session
    _poser_cache(tmp_path, _contrat(seuil=0.90))

    res = _appel(tmp_path, sess, seuil_3f=0.90)

    assert backend["n"] == 0
    assert res["reused"] is True


# ── mode déduit : None ne veut pas dire « n'importe lequel » ───────────


def test_a_deduced_mode_is_compared_too(session, backend, tmp_path):
    """``filter_mode=None`` + ``type_pattern`` attend ``geometric_type_filter``.

    Un contrat aux mêmes motifs mais en mode ``geometric`` décrit une autre
    sélection — et un autre total.
    """
    sess, _ = session
    _poser_cache(tmp_path, _contrat(mode="geometric"))

    _appel(tmp_path, sess, filter_mode=None)

    assert backend["n"] == 1


def test_a_correctly_deduced_mode_is_reused(session, backend, tmp_path):
    """Sans ce cas, une comparaison toujours fausse passerait pour correcte."""
    sess, _ = session
    _poser_cache(tmp_path, _contrat(mode="geometric_type_filter"))

    res = _appel(tmp_path, sess, filter_mode=None)

    assert backend["n"] == 0
    assert res["reused"] is True


@pytest.mark.parametrize(
    ("filter_mode", "layer_pattern", "type_pattern", "attendu"),
    [
        (None, None, None, "geometric"),
        (None, None, TYPE_PATTERN, "geometric_type_filter"),
        (None, r"221", None, "layer_type_filter"),
        (None, r"221", TYPE_PATTERN, "layer_type_filter"),
        ("geometric_type_filter", None, TYPE_PATTERN, "geometric_type_filter"),
    ],
)
def test_expected_mode_matches_the_backend_rule(filter_mode, layer_pattern, type_pattern, attendu):
    """La règle locale ne doit pas diverger de celle du backend.

    Elle est répliquée — et non appelée — pour que le contrôle de cache reste
    utilisable sans l'extra ``geometry``. Ce test est le prix de cette autonomie.
    """
    assert avp_autocompute.expected_filter_mode(filter_mode, layer_pattern, type_pattern) == attendu

    pytest.importorskip("ifc_openshell_mcp")
    assert geometry_backend.resolve_filter_mode(filter_mode, layer_pattern, type_pattern) == attendu
