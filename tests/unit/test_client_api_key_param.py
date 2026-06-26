"""Le param ``api_key`` de ``BIMDataClient`` (clé par instance).

Permet à la façade web ``/mcp-setup`` d'injecter une clé propre à une
session **sans muter** le ``config`` global (isolation multi-session).
"""

from __future__ import annotations

from audit_bim import config
from audit_bim.extraction.client import BIMDataClient


def test_instance_api_key_used_as_apikey_header():
    c = BIMDataClient(api_key="INSTANCE_KEY", cloud_id=1, project_id=2, model_id=3)
    assert c.session.headers["Authorization"] == "ApiKey INSTANCE_KEY"


def test_instance_api_key_does_not_mutate_global_config(monkeypatch):
    monkeypatch.setattr(config, "API_KEY", "GLOBAL_KEY")
    c = BIMDataClient(api_key="INSTANCE_KEY", cloud_id=1, project_id=2, model_id=3)
    # La clé d'instance prime…
    assert c.session.headers["Authorization"] == "ApiKey INSTANCE_KEY"
    # …et le config global n'est pas modifié.
    assert config.API_KEY == "GLOBAL_KEY"


def test_two_instances_isolated_keys():
    c1 = BIMDataClient(api_key="K1", cloud_id=1, project_id=1, model_id=1)
    c2 = BIMDataClient(api_key="K2", cloud_id=2, project_id=2, model_id=2)
    assert c1.session.headers["Authorization"] == "ApiKey K1"
    assert c2.session.headers["Authorization"] == "ApiKey K2"


def test_access_token_takes_precedence_over_api_key():
    c = BIMDataClient(access_token="TOK", api_key="K", cloud_id=1, project_id=2, model_id=3)
    assert c.session.headers["Authorization"] == "Bearer TOK"


def test_api_key_falls_back_to_config(monkeypatch):
    monkeypatch.setattr(config, "API_KEY", "GLOBAL_KEY")
    c = BIMDataClient(cloud_id=1, project_id=2, model_id=3)
    assert c.session.headers["Authorization"] == "ApiKey GLOBAL_KEY"
