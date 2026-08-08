"""Le refus de contexte est une valeur nommée, pas un ``dict`` au milieu du flot.

``_validate_avp_context`` rend un :class:`AvpContextCheck` : soit une identité
résolue, soit une réponse de refus — jamais les deux, jamais aucune. L'appelant
écrit ``if context.response is not None: return context.response``, et le refus
cesse d'être un ``return`` perdu parmi ceux de la génération.

Le point qui ne doit pas se perdre dans l'extraction : ``project_name``,
``project_code`` et ``project_phase`` nomment le fichier remis au client. Ils
sont **incontournables**, et ``confirm_context`` ne les couvre pas — il ne lève
que ce qui reste interne au document.
"""

from __future__ import annotations

import pytest

from audit_bim.extraction.model_data import ModelSnapshot
from audit_bim.mcp.session import _Session, current_session
from audit_bim.profiles.i3f.tools_reporting import (
    AvpContextCheck,
    AvpIdentityContext,
    _validate_avp_context,
)


@pytest.fixture
def session(tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIT_OUTPUT_DIR", str(tmp_path))
    monkeypatch.setenv("AUDIT_INPUT_DIR", str(tmp_path))
    sess = _Session()
    sess.snapshot = ModelSnapshot(
        project={"name": "Dieppe"},
        model={"name": "DIEPPE-7427L.ifc"},
        spaces=[{"uuid": "SP1", "type": "IfcSpace", "name": "SEJOUR"}],
        elements=[{"uuid": "W1", "type": "IfcWall", "name": "Mur"}],
    ).index()
    token = current_session.set(sess)
    try:
        yield sess
    finally:
        current_session.reset(token)


def _valider(**kwargs):
    from audit_bim.reporting.avp_sources import AvpSourcePaths, load_sources

    base = dict(
        controle_xlsx=None,
        shab_xlsx=None,
        zones_espaces_xlsx=None,
        enveloppe_xlsx=None,
        menuiseries_xlsx=None,
        plancher_xlsx=None,
        project_name="Dieppe Chantier",
        project_code="7427L",
        phase="AVP",
        auditor_name="S. Limouzi",
        auteur_controle=None,
        auditor=None,
        confirm_context=False,
        AvpSourcePaths=AvpSourcePaths,
        load_sources=load_sources,
    )
    base.update(kwargs)
    return _validate_avp_context(**base)


def test_a_complete_context_yields_an_identity_and_no_response(session):
    """Chemin nominal : une identité, aucun refus."""
    check = _valider()
    assert check.response is None
    assert isinstance(check.identity, AvpIdentityContext)
    assert check.identity.project_name == "Dieppe Chantier"
    assert check.identity.project_code == "7427L"
    assert check.identity.phase == "AVP"
    assert check.identity.auteur_controle == "S. Limouzi"


@pytest.mark.parametrize("champ", ["project_name", "project_code", "phase"])
def test_identity_fields_cannot_be_bypassed_by_confirm_context(session, champ):
    """**Non-vacuité exigée** : ``confirm_context`` ne lève pas ces trois-là.

    Ils nomment le fichier remis au client. Si l'extraction avait laissé
    ``identity_missing`` se diluer dans ``missing``, ``confirm_context=True``
    aurait suffi à générer un livrable au nom incomplet — silencieusement.
    """
    check = _valider(**{champ: None}, confirm_context=True)

    assert check.identity is None
    assert check.response is not None
    assert check.response["status"] == "needs_context"
    assert "OBLIGATOIRES" in check.response["next_step"]


def test_a_non_identity_field_is_covered_by_confirm_context(session):
    """Contre-épreuve : sans elle, le test précédent prouverait « tout refuse ».

    L'auteur du contrôle reste interne au document : ``confirm_context`` le
    couvre, et la génération doit passer.
    """
    sans_auteur = _valider(auditor_name=None)
    assert sans_auteur.response is not None, "prémisse : sans auteur, on demande"

    force = _valider(auditor_name=None, confirm_context=True)
    assert force.response is None
    assert force.identity is not None


def test_a_missing_snapshot_is_a_context_refusal(session):
    """La garde « pas de maquette » est repliée ici : une seule sortie de contexte."""
    session.snapshot = None
    session.result = None

    check = _valider()
    assert check.identity is None
    assert check.response["missing"] == ["snapshot"]


def test_the_check_cannot_carry_both_or_neither():
    """L'invariant est gardé par le type, pas par la discipline de l'appelant."""
    with pytest.raises(ValueError, match="exactement une identité OU un refus"):
        AvpContextCheck(identity=None, response=None)

    with pytest.raises(ValueError, match="exactement une identité OU un refus"):
        AvpContextCheck(
            identity=AvpIdentityContext("N", "C", "AVP", "A", None, None),
            response={"status": "needs_context"},
        )
