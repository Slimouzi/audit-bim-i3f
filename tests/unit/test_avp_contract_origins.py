"""Caractérisation : d'où vient un contrat, et qui repasse la garde de provenance.

Écrit **avant** la factorisation des deux blocs contrat de
``generate_avp_i3f_pack`` (lot R1). Son rôle est de figer le comportement
observable **avant** de déplacer le code, pour qu'un écart se voie.

Le point délicat, et la raison d'être de ce fichier : les deux contrats n'ont
pas le même nombre d'origines, et la garde de provenance ne s'applique pas aux
mêmes.

``envelope_quantities/v1`` — **trois** origines :

- ``parametre`` — chemin passé par l'appelant. Aucun contrôle de cible n'a été
  fait : la garde est **obligatoire** ;
- ``detecte`` — fichier trouvé sur disque par ``_auto_envelope_json``, qui l'a
  **déjà corrélé au modèle actif** via ``_envelope_json_matches_model``. La
  garde ne s'applique pas — la corrélation a eu lieu en amont ;
- ``calcule`` — produit pendant cette exécution, donc par construction du bon
  modèle.

``computed_base_quantities/v1`` — **deux** origines seulement : ``parametre`` et
``calcule``. Il n'existe pas de détection sur disque pour ce contrat.

C'est pourquoi l'origine doit être **donnée** au futur helper commun et non
redevinée depuis la forme du chemin : « ce n'est pas nous qui l'avons calculé »
ne veut pas dire « l'appelant l'a fourni ».
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from audit_bim.extraction.model_data import ModelSnapshot
from audit_bim.mcp.session import _Session, current_session
from audit_bim.profiles.i3f import tools_reporting as tr

MODELE = "DIEPPE-7427L.ifc"
AUTRE_MODELE = "UN-AUTRE-MODELE.ifc"


def _snapshot() -> ModelSnapshot:
    return ModelSnapshot(
        project={"name": "Dieppe"},
        model={"name": MODELE},
        spaces=[{"uuid": "SP1", "type": "IfcSpace", "name": "SEJOUR", "longname": "SEJOUR"}],
        elements=[
            {"uuid": "W1", "type": "IfcWall", "name": "Mur ext"},
            {"uuid": "W2", "type": "IfcWindow", "name": "F25"},
        ],
    ).index()


@pytest.fixture
def session(tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIT_OUTPUT_DIR", str(tmp_path))
    monkeypatch.setenv("AUDIT_INPUT_DIR", str(tmp_path))
    sess = _Session()
    sess.snapshot = _snapshot()
    token = current_session.set(sess)
    try:
        yield sess, tmp_path
    finally:
        current_session.reset(token)


def _enveloppe(ifc_file: str = MODELE) -> dict:
    return {
        "schema": "envelope_quantities/v1",
        "source": {
            "producer": "ifc-geometry",
            "tool": "extract_envelope_surfaces",
            "version": "0.6.1",
            "ifc_file": ifc_file,
        },
        "par_type": [{"type": "Mur ext", "net_side_area_m2": 120.0, "n": 4}],
    }


def _quantites(ifc_file: str = MODELE) -> dict:
    return {
        "schema": "computed_base_quantities/v1",
        "source": {
            "producer": "ifc-geometry",
            "tool": "complete_ifc_base_quantities",
            "version": "0.6.1",
            "ifc_file": ifc_file,
        },
        "elements": [],
    }


def _ecrire(dossier: Path, nom: str, charge: dict) -> Path:
    chemin = dossier / nom
    chemin.write_text(json.dumps(charge, ensure_ascii=False), encoding="utf-8")
    return chemin


# ---------------------------------------------------------------------------
# 1. Les origines existantes, mesurées sur le code — pas supposées.
# ---------------------------------------------------------------------------


def test_the_envelope_contract_has_a_detection_path():
    """L'enveloppe se détecte sur disque ; c'est sa troisième origine."""
    assert hasattr(tr, "_auto_envelope_json")
    assert hasattr(tr, "_envelope_json_matches_model")


def test_the_quantities_contract_has_no_detection_path():
    """Les quantités n'ont que deux origines : paramètre ou calcul.

    Si une détection apparaissait un jour, ce test tomberait — et il faudrait
    alors décider si elle échappe à la garde, comme pour l'enveloppe.
    """
    candidats = [n for n in dir(tr) if "auto" in n and "quantit" in n.lower()]
    assert not candidats, candidats


# ---------------------------------------------------------------------------
# 2. Le trou critique : un contrat DÉTECTÉ ne repasse pas la garde.
# ---------------------------------------------------------------------------


def test_a_detected_envelope_is_correlated_before_being_used(session, monkeypatch):
    """Un fichier détecté est corrélé au modèle **avant** d'être retenu.

    C'est ce qui justifie qu'il échappe à la garde de provenance : la
    vérification a eu lieu, ailleurs et plus tôt.
    """
    _sess, tmp = session
    _ecrire(tmp, f"{Path(MODELE).stem}_envelope.json", _enveloppe())

    vus: list[Path] = []

    def _corrélé(chemin):
        vus.append(Path(chemin))
        return True

    monkeypatch.setattr(tr, "_envelope_json_matches_model", _corrélé)
    trouve = tr._auto_envelope_json()

    assert trouve is not None, "prémisse : le fichier doit être détecté"
    assert vus, "la détection doit passer par la corrélation au modèle actif"


def test_a_detected_envelope_of_another_model_is_refused(session, monkeypatch):
    """Non-corrélé ⇒ non retenu. C'est la garde équivalente, en amont."""
    _sess, tmp = session
    _ecrire(tmp, f"{Path(MODELE).stem}_envelope.json", _enveloppe(ifc_file=AUTRE_MODELE))

    monkeypatch.setattr(tr, "_envelope_json_matches_model", lambda _c: False)
    assert tr._auto_envelope_json() is None


def test_detection_is_not_treated_as_a_parameter(session, monkeypatch):
    """**Non-vacuité exigée** : ``detecte`` ne doit pas devenir ``parametre``.

    Si la factorisation traitait un fichier détecté comme un chemin fourni, la
    garde de provenance s'appliquerait à lui. Ce test échoue dans ce cas :
    il détecte un fichier d'un AUTRE modèle tout en forçant la corrélation à
    vrai — situation impossible en vrai, mais qui isole la question posée :
    *qui décide, la corrélation amont ou la garde aval ?*
    """
    _sess, tmp = session
    _ecrire(tmp, f"{Path(MODELE).stem}_envelope.json", _enveloppe(ifc_file=AUTRE_MODELE))
    monkeypatch.setattr(tr, "_envelope_json_matches_model", lambda _c: True)

    detecte = tr._auto_envelope_json()
    assert detecte is not None, "prémisse : la corrélation forcée doit retenir le fichier"

    # Le même fichier, s'il était PASSÉ EN PARAMÈTRE, serait refusé par la
    # garde de provenance — c'est exactement la différence de traitement.
    from audit_bim.reporting.avp_autocompute import ContractModelMismatch

    with pytest.raises(ContractModelMismatch):
        tr._guard_contract_provenance(Path(detecte), parametre="envelope_json")


# ---------------------------------------------------------------------------
# 3. Scénarios communs aux deux contrats — paramétrés, pas dupliqués.
# ---------------------------------------------------------------------------

CONTRATS = (
    pytest.param("envelope_json", _enveloppe, "_envelope.json", id="enveloppe"),
    pytest.param("computed_quantities_json", _quantites, "_quantities.json", id="quantites"),
)


@pytest.mark.parametrize(("parametre", "charge", "suffixe"), CONTRATS)
def test_a_parameter_path_of_another_model_is_refused(session, parametre, charge, suffixe):
    """Origine ``parametre`` : la garde s'applique, quel que soit le contrat."""
    _sess, tmp = session
    chemin = _ecrire(tmp, f"autre{suffixe}", charge(ifc_file=AUTRE_MODELE))

    from audit_bim.reporting.avp_autocompute import ContractModelMismatch

    with pytest.raises(ContractModelMismatch):
        tr._guard_contract_provenance(chemin, parametre=parametre)


@pytest.mark.parametrize(("parametre", "charge", "suffixe"), CONTRATS)
def test_a_parameter_path_of_the_active_model_passes(session, parametre, charge, suffixe):
    """Succès nominal : même modèle ⇒ la garde laisse passer et rend l'IFC."""
    _sess, tmp = session
    chemin = _ecrire(tmp, f"bon{suffixe}", charge(ifc_file=MODELE))

    assert tr._guard_contract_provenance(chemin, parametre=parametre) == MODELE


@pytest.mark.parametrize(("parametre", "charge", "suffixe"), CONTRATS)
def test_a_missing_path_yields_no_provenance_and_does_not_raise(
    session, parametre, charge, suffixe
):
    """Chemin absent : la garde rend ``None``, elle ne lève **pas**.

    Comportement mesuré, contraire à ce qu'on suppose spontanément : la garde
    ne refuse pas un fichier illisible, elle constate seulement qu'aucune
    provenance n'est déclarée. Le refus d'un chemin absent appartient à la
    lecture (``safe_input_path`` puis le lecteur de contrat), pas à elle.

    C'est une contrainte forte sur la factorisation : un helper commun ne doit
    pas supposer que la garde protège de l'absence — sinon il retirerait
    silencieusement le contrôle qui le fait vraiment.
    """
    _sess, tmp = session
    absent = tmp / f"jamais-ecrit{suffixe}"
    assert not absent.exists(), "prémisse : le fichier ne doit pas exister"

    assert tr._guard_contract_provenance(absent, parametre=parametre) is None


@pytest.mark.parametrize(("parametre", "charge", "suffixe"), CONTRATS)
def test_reading_is_what_refuses_a_missing_path(session, parametre, charge, suffixe):
    """Contre-partie du test précédent : quelque chose DOIT refuser l'absence."""
    _sess, tmp = session
    absent = tmp / f"jamais-ecrit{suffixe}"

    from bim_core.paths import safe_input_path

    with pytest.raises((FileNotFoundError, ValueError, OSError)):
        safe_input_path(str(absent), allowed_extensions={".json"})


def test_the_mismatch_payload_names_the_parameter_at_fault():
    """La forme d'erreur est commune : c'est ce qui rend la factorisation légitime."""
    from audit_bim.reporting.avp_autocompute import ContractModelMismatch

    exc = ContractModelMismatch(
        f"contrat calculé pour {AUTRE_MODELE}, modèle actif {MODELE}",
        parametre="envelope_json",
        provenance=AUTRE_MODELE,
    )
    charge = tr._contract_mismatch_payload(exc)

    assert charge["status"] == "error"
    assert "envelope_json" in json.dumps(charge, ensure_ascii=False)
