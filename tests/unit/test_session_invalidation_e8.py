"""E8 (audit profond 2ᵉ passe) — ``set_active_model`` invalide le store de
suggestions.

Le store est construit sur les UUIDs du modèle actif. Sans invalidation au
changement de modèle, un plan de classifications scellé sur la **nouvelle** cible
porterait les UUIDs de l'**ancien** modèle → écritures parasites (``validate_target``
ne contrôle que la cible, pas la provenance des items).
"""

from __future__ import annotations

from unittest.mock import patch

from audit_bim.mcp import tools_session as ts
from audit_bim.mcp.session import _Session, current_session


def _run_with_session(fn):
    sess = _Session()
    token = current_session.set(sess)
    try:
        return fn(sess)
    finally:
        current_session.reset(token)


def test_set_active_model_invalidates_suggestion_store():
    def body(sess):
        sess.suggestion_store = object()  # store du modèle précédent
        sess.snapshot = object()
        sess.result = object()
        with patch.object(ts, "BIMDataClient"):
            ts.set_active_model(cloud_id="c", project_id="p", model_id="m")
        # les 3 caches downstream sont invalidés
        assert sess.suggestion_store is None
        assert sess.snapshot is None
        assert sess.result is None

    _run_with_session(body)
