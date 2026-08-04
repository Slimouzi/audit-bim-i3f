"""Tests du téléchargement du .ifc source (Lot 1) : streaming, cache, plafond."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from audit_bim.extraction.ifc_download import download_model_ifc


class _FakeResp:
    def __init__(self, chunks: list[bytes], raise_after: int | None = None):
        self._chunks = chunks
        self._raise_after = raise_after  # lève une erreur réseau après N chunks

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size=None):
        for i, c in enumerate(self._chunks):
            if self._raise_after is not None and i >= self._raise_after:
                raise ConnectionError("réseau interrompu au milieu du streaming")
            yield c

    def close(self):
        return None


class _FakeSession:
    def __init__(self, chunks: list[bytes], raise_after: int | None = None):
        self._chunks = chunks
        self._raise_after = raise_after
        self.calls = 0

    def get(self, url, stream=False, timeout=None):
        self.calls += 1
        return _FakeResp(self._chunks, raise_after=self._raise_after)


class _FakeClient:
    def __init__(
        self,
        model: dict,
        chunks: list[bytes],
        *,
        cloud_id: str = "34140",
        project_id: str = "3281472",
        raise_after: int | None = None,
    ):
        self._model = model
        self.session = _FakeSession(chunks, raise_after=raise_after)
        self.cloud_id = cloud_id
        self.project_id = project_id
        self.model_id = model.get("id")
        self.timeout = 60

    def get_model(self):
        return self._model


_MODEL = {
    "id": "1744246",
    "modified_date": "2026-05-25T10:00:00Z",
    "document": {"file": "https://signed.example/f.ifc"},
}


def test_download_streams_writes_and_returns_metadata(tmp_path):
    chunks = [b"ISO-10303-21;\n", b"DATA;\nENDSEC;\n"]
    client = _FakeClient(_MODEL, chunks)
    res = download_model_ifc(client, cache_dir=str(tmp_path), max_mb=500)
    assert res["from_cache"] is False
    assert res["model_id"] == "1744246"
    assert res["size_bytes"] == sum(len(c) for c in chunks)
    p = Path(res["path"])
    assert p.exists() and p.parent.name == "ifc"
    assert p.read_bytes() == b"".join(chunks)


def test_cache_hit_avoids_second_download(tmp_path):
    client = _FakeClient(_MODEL, [b"IFC"])
    r1 = download_model_ifc(client, cache_dir=str(tmp_path), max_mb=500)
    r2 = download_model_ifc(client, cache_dir=str(tmp_path), max_mb=500)
    assert r1["from_cache"] is False and r2["from_cache"] is True
    assert client.session.calls == 1  # un seul GET réseau


def test_overwrite_forces_redownload(tmp_path):
    client = _FakeClient(_MODEL, [b"IFC"])
    download_model_ifc(client, cache_dir=str(tmp_path), max_mb=500)
    r = download_model_ifc(client, cache_dir=str(tmp_path), max_mb=500, overwrite=True)
    assert r["from_cache"] is False
    assert client.session.calls == 2


def test_size_limit_aborts_and_cleans(tmp_path):
    chunks = [b"x" * (1024 * 1024)] * 3  # 3 Mo
    client = _FakeClient(_MODEL, chunks)
    with pytest.raises(ValueError, match="volumineux"):
        download_model_ifc(client, cache_dir=str(tmp_path), max_mb=2)
    ifc_dir = tmp_path / "ifc"
    assert list(ifc_dir.glob("*.part")) == []  # partiel nettoyé
    assert list(ifc_dir.glob("*.ifc")) == []  # cible jamais matérialisée


def test_missing_ifc_url_raises(tmp_path):
    client = _FakeClient({"id": "1", "modified_date": "d"}, [b"IFC"])
    with pytest.raises(ValueError, match="introuvable"):
        download_model_ifc(client, cache_dir=str(tmp_path), max_mb=500)


def test_cache_key_invalidated_on_new_modified_date(tmp_path):
    c1 = _FakeClient(dict(_MODEL, modified_date="2026-05-25"), [b"A"])
    c2 = _FakeClient(dict(_MODEL, modified_date="2026-06-01"), [b"BB"])
    p1 = download_model_ifc(c1, cache_dir=str(tmp_path), max_mb=500)["path"]
    p2 = download_model_ifc(c2, cache_dir=str(tmp_path), max_mb=500)["path"]
    assert p1 != p2  # une republication = nouvelle clé de cache


def test_cache_key_no_inter_project_collision(tmp_path):
    # Même model_id + modified_date, projets/clouds différents → clés distinctes.
    a = _FakeClient(_MODEL, [b"A"], cloud_id="34140", project_id="3281472")
    b = _FakeClient(_MODEL, [b"BB"], cloud_id="33617", project_id="2698917")
    ra = download_model_ifc(a, cache_dir=str(tmp_path), max_mb=500)
    rb = download_model_ifc(b, cache_dir=str(tmp_path), max_mb=500)
    assert ra["path"] != rb["path"]
    # Chacun a bien son propre contenu (pas d'écrasement croisé).
    assert Path(ra["path"]).read_bytes() == b"A"
    assert Path(rb["path"]).read_bytes() == b"BB"


def test_midstream_error_cleans_part_and_raises(tmp_path):
    # iter_content lève après le 1er chunk → exception propagée, .part nettoyé,
    # aucune cible matérialisée.
    client = _FakeClient(_MODEL, [b"x" * 1024, b"y" * 1024], raise_after=1)
    with pytest.raises(ConnectionError):
        download_model_ifc(client, cache_dir=str(tmp_path), max_mb=500)
    ifc_dir = tmp_path / "ifc"
    assert list(ifc_dir.glob("*.part")) == []
    assert list(ifc_dir.glob("*.ifc")) == []


def test_tool_registered():
    """Le tool est bien exposé par le registre MCP.

    Le ré-export ``server.download_model_ifc`` n'est plus vérifié ici : depuis
    E3-B, la compat est exercée au seul endroit qui la revendique
    (``test_server_compat_reexports.py``). La laisser ici en ferait à nouveau
    un chemin que personne ne peut retirer.
    """
    from audit_bim.mcp.app import register_all

    mcp = register_all()
    names = [t.name for t in asyncio.run(mcp.list_tools())]
    assert "download_model_ifc" in names
