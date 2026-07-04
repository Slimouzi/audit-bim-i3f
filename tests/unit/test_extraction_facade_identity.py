"""Gate d'identité : les anciens chemins ``audit_bim.extraction.*`` pointent bien
vers les symboles extraits dans ``bimdata-read`` / ``bim-core`` (façade).

Ces tests garantissent que le découpage n'a pas dupliqué de logique : les
ré-exports sont *les mêmes objets*, et ``BIMDataClient`` hérite de la lecture
(`bimdata-read`) **et** de l'écriture (`bimdata-write`) — aucun transport local.
"""

from __future__ import annotations

import bim_core
import bimdata_read
import bimdata_write

from audit_bim.extraction import client as ex_client
from audit_bim.extraction import model_data as ex_model_data
from audit_bim.extraction import snapshot_cache as ex_cache


def test_model_snapshot_is_bim_core():
    assert ex_model_data.ModelSnapshot is bim_core.ModelSnapshot


def test_extract_snapshot_is_bimdata_read():
    assert ex_model_data.extract_snapshot is bimdata_read.extract_snapshot


def test_cache_symbols_are_bimdata_read():
    assert ex_cache.cached_extract_snapshot is bimdata_read.cached_extract_snapshot
    assert ex_cache.save_snapshot_to_cache is bimdata_read.save_snapshot_to_cache
    assert ex_cache.load_snapshot_from_cache is bimdata_read.load_snapshot_from_cache


def test_client_inherits_read_and_write():
    # La façade hérite écriture (bimdata-write) → lecture (bimdata-read).
    assert issubclass(ex_client.BIMDataClient, bimdata_write.BIMDataWriteClient)
    assert issubclass(ex_client.BIMDataClient, bimdata_read.BIMDataReadClient)
    # Lecture héritée.
    for name in ("get_project", "get_model", "get_raw_elements", "get_structure_tree", "_get"):
        assert hasattr(ex_client.BIMDataClient, name)
    # Écritures = méthodes NOMMÉES, définies dans bimdata-write (pas en local,
    # pas dans le client lecture).
    for name in (
        "create_classification",
        "assign_classification_elements",
        "write_element_propertyset",
        "create_bcf_full_topic",
        "_post",
    ):
        assert name in vars(bimdata_write.BIMDataWriteClient)
        assert name not in vars(ex_client.BIMDataClient)  # aucun transport local
        assert not hasattr(bimdata_read.BIMDataReadClient, name)


def test_no_raw_post_in_audit_bim():
    """Aucun transport ``_post`` brut ne subsiste dans le code applicatif :
    ``BIMDataClient`` ne redéfinit pas ``_post`` (il vient de bimdata-write)."""
    assert "_post" not in vars(ex_client.BIMDataClient)


def test_auth_error_and_retry_adapter_reexported():
    assert ex_client.BIMDataAuthError is bimdata_read.BIMDataAuthError
    # _build_retry_adapter reste importable depuis l'ancien chemin (test retries).
    from bimdata_read.client import _build_retry_adapter as bd_retry

    assert ex_client._build_retry_adapter is bd_retry


def test_client_construction_uses_config_fallback(monkeypatch):
    # Sans IDs passés, le constructeur retombe sur config.* (auth via API_KEY).
    from audit_bim import config

    monkeypatch.setattr(config, "API_KEY", "k", raising=False)
    monkeypatch.setattr(config, "ACCESS_TOKEN", None, raising=False)
    monkeypatch.setattr(config, "CLOUD_ID", 11, raising=False)
    monkeypatch.setattr(config, "PROJECT_ID", 22, raising=False)
    monkeypatch.setattr(config, "MODEL_ID", 33, raising=False)
    c = ex_client.BIMDataClient()
    assert (c.cloud_id, c.project_id, c.model_id) == (11, 22, 33)
    assert c.session.headers["Authorization"] == "ApiKey k"
