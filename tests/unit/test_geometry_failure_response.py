"""Le refus « calcul géométrique impossible » a une seule forme.

Les deux contrats — enveloppe et quantités calculées — échouent identiquement
sur ``GeometryInputMissing`` / ``GeometryBackendUnavailable``. Seule la clé
``error`` les distingue. Le helper factorise ces treize lignes, sans toucher ni
aux producteurs, ni aux lecteurs, ni au déclenchement, ni aux traitements aval :
la mesure a montré qu'ils n'ont **rien** d'autre en commun.

Deux niveaux de test, et le premier ne suffit pas : tester le helper seul
prouverait qu'il construit un dict, pas que les deux blocs l'emploient.
"""

from __future__ import annotations

import pytest

from audit_bim.profiles.i3f.tools_reporting import _geometry_failure_response


class _EchecAvecMissing(Exception):
    """Forme réelle : le backend dit **ce qui** manque."""

    def __init__(self, message: str, missing: str):
        super().__init__(message)
        self.missing = missing


class _EchecSansMissing(Exception):
    """Forme dégradée : une panne du backend sans entrée nommée."""


def test_the_response_names_what_the_backend_reported_missing():
    charge = _geometry_failure_response(
        _EchecAvecMissing("Fournir ``ifc_path``.", missing="ifc_path"),
        error="cannot_compute_envelope",
    )

    assert charge["status"] == "needs_context"
    assert charge["error"] == "cannot_compute_envelope"
    assert charge["missing"] == ["ifc_path"]
    assert charge["questions"] == [{"key": "ifc_path", "question": "Fournir ``ifc_path``."}]


def test_the_fallback_is_geometry_backend_when_nothing_is_named():
    """Verrou du repli : sans attribut ``missing``, la clé reste exploitable."""
    charge = _geometry_failure_response(
        _EchecSansMissing("Backend indisponible."), error="cannot_compute_quantities"
    )

    assert charge["missing"] == ["geometry_backend"]
    assert charge["questions"][0]["key"] == "geometry_backend"


def test_the_list_and_the_question_always_designate_the_same_thing():
    """``missing`` est calculé une fois : les deux ne peuvent pas diverger.

    Avant le helper, deux ``getattr`` séparés lisaient l'attribut chacun de leur
    côté. Ce test fige l'invariant plutôt que l'implémentation : on emploie une
    exception dont l'attribut CHANGE entre deux lectures — si le helper le
    relisait, la liste et la question ne se correspondraient plus.
    """

    class _Instable(Exception):
        _valeurs = iter(["premier", "second", "troisieme"])

        @property
        def missing(self):
            return next(self._valeurs)

    charge = _geometry_failure_response(_Instable("bruit"), error="cannot_compute_envelope")
    assert charge["missing"] == [charge["questions"][0]["key"]]


@pytest.mark.parametrize("error", ["cannot_compute_envelope", "cannot_compute_quantities"])
def test_only_the_error_key_distinguishes_the_two_contracts(error):
    """La forme est identique ; c'est ce qui justifie la factorisation."""
    charge = _geometry_failure_response(_EchecAvecMissing("m", missing="ifc_path"), error=error)
    assert charge["error"] == error
    assert set(charge) == {"status", "missing", "error", "message", "questions"}
