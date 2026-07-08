"""Robustesse déploiement — l'extraction du snapshot (une LECTURE) ne doit pas
planter quand la racine d'export (``AUDIT_OUTPUT_DIR``) est en **lecture seule**.

Symptôme terrain : conteneur avec ``/out`` monté read-only → ``get_export_root()``
échoue son ``mkdir`` (Errno 30) dès qu'on calcule le dossier de cache, même avec
``use_cache=False`` (l'appel était inconditionnel). On dégrade en extraction sans
cache.
"""

from __future__ import annotations

from unittest.mock import patch

from audit_bim.extraction.model_data import ModelSnapshot
from audit_bim.mcp import tools_session as ts
from audit_bim.mcp.session import _Session, current_session


def _with_session(fn):
    sess = _Session()
    sess.client = object()  # ensure_client() ne vérifie que non-None
    token = current_session.set(sess)
    try:
        return fn(sess)
    finally:
        current_session.reset(token)


def _snap() -> ModelSnapshot:
    return ModelSnapshot(model={"name": "M.ifc"}, buildings=[{"uuid": "b1"}]).index()


def test_extract_model_snapshot_degrades_on_readonly_root():
    def body(_sess):
        with (
            patch.object(ts, "safe_export_dir", side_effect=OSError(30, "Read-only file system")),
            patch.object(ts, "extract_snapshot", return_value=_snap()) as m_extract,
            patch.object(ts, "cached_extract_snapshot") as m_cached,
        ):
            out = ts.extract_model_snapshot(use_cache=True)
        assert out["from_cache"] is False
        m_cached.assert_not_called()  # cache court-circuité, pas de crash
        m_extract.assert_called_once()

    _with_session(body)


def test_use_cache_false_never_touches_export_root():
    # Avec use_cache=False, on ne doit même pas appeler safe_export_dir (donc pas
    # de mkdir sur une racine read-only).
    def body(_sess):
        with (
            patch.object(ts, "safe_export_dir") as m_safe,
            patch.object(ts, "extract_snapshot", return_value=_snap()),
        ):
            out = ts.extract_model_snapshot(use_cache=False)
        assert out["from_cache"] is False
        m_safe.assert_not_called()

    _with_session(body)
