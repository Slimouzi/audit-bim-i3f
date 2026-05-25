"""Fixtures pour les tests d'intégration HTTP.

Démarre un vrai serveur MCP en sous-processus (transport
``streamable-http``) sur un port libre, attend qu'il accepte les
connexions, puis le termine en fin de session.

Les tests d'intégration n'ont **pas besoin** de BIMData credentials :
on teste les tools sans dépendance externe (``list_tools``,
``project_context_questions``, ``list_classification_systems``).
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
import requests


def _find_free_port() -> int:
    """Réserve un port TCP libre éphémère et le renvoie."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_http(url: str, timeout_s: float = 15.0) -> None:
    """Attend qu'une URL HTTP réponde (n'importe quel code < 600).

    Args:
        url: URL à interroger.
        timeout_s: Timeout maximum cumulé en secondes.

    Raises:
        TimeoutError: Si le serveur n'a pas répondu dans les délais.
    """
    deadline = time.time() + timeout_s
    last_exc: Exception | None = None
    while time.time() < deadline:
        try:
            r = requests.get(url, timeout=1.0)
            # Tout code valide (même 406 / 404) signifie que le serveur écoute.
            if 100 <= r.status_code < 600:
                return
        except Exception as e:
            last_exc = e
        time.sleep(0.25)
    raise TimeoutError(f"Serveur {url} non démarré après {timeout_s}s ({last_exc!r})")


def _spawn_mcp_server(extra_env: dict[str, str] | None = None) -> tuple[subprocess.Popen, dict]:
    """Démarre un serveur MCP streamable-http en sous-process.

    Args:
        extra_env: Variables d'env à fusionner avec ``os.environ`` (utile
            pour activer ``AUDIT_BIM_API_KEY`` sur certaines fixtures).

    Returns:
        Tuple ``(proc, info)`` — ``info`` est le dict yieldé par les
        fixtures (``url``, ``host``, ``port``, ``mcp_endpoint``).
    """
    port = _find_free_port()
    host = "127.0.0.1"
    url = f"http://{host}:{port}"
    mcp_endpoint = f"{url}/mcp"

    repo_root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env.setdefault("BIMDATA_API_KEY", "dummy-for-integration-tests")
    if extra_env:
        env.update(extra_env)

    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "audit_bim.mcp",
            "--transport",
            "streamable-http",
            "--host",
            host,
            "--port",
            str(port),
        ],
        cwd=str(repo_root),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        _wait_for_http(mcp_endpoint, timeout_s=20.0)
    except Exception as exc:
        proc.terminate()
        out, err = proc.communicate(timeout=5)
        raise RuntimeError(
            f"Serveur MCP non démarré.\n"
            f"stdout: {out.decode(errors='ignore')[:2000]}\n"
            f"stderr: {err.decode(errors='ignore')[:2000]}"
        ) from exc

    return proc, {"url": url, "host": host, "port": port, "mcp_endpoint": mcp_endpoint}


def _terminate(proc: subprocess.Popen) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.fixture(scope="session")
def mcp_http_server() -> Iterator[dict]:
    """Démarre le serveur MCP en streamable-http pour la session de tests.

    Variante sans clé service — couvre les tools sans dépendance externe.
    Pour un serveur protégé par ``AUDIT_BIM_API_KEY``, voir
    :func:`mcp_http_server_with_api_key`.

    Yields:
        Dict ``{url, host, port, mcp_endpoint}`` pour les tests.
    """
    proc, info = _spawn_mcp_server()
    try:
        yield info
    finally:
        _terminate(proc)


# Clé service utilisée par les tests d'auth — volontairement courte +
# non-secrète, lisible dans les logs pour le débug.
TEST_API_KEY = "test-secret-xyz123"


@pytest.fixture(scope="session")
def mcp_http_server_with_api_key(tmp_path_factory) -> Iterator[dict]:
    """Variante avec ``AUDIT_BIM_API_KEY`` activé.

    Avec une clé service définie, ``assert_startup_config`` exige aussi
    ``AUDIT_INPUT_DIR`` — on fournit une racine éphémère pour que le
    serveur démarre. La racine reste vide : les tests d'auth ne lisent
    aucun fichier.

    Yields:
        Dict ``{url, host, port, mcp_endpoint, api_key}`` — la clé est
        celle attendue par le serveur, à utiliser dans les headers du
        client de test.
    """
    input_dir = tmp_path_factory.mktemp("audit_input_session")
    proc, info = _spawn_mcp_server(
        {
            "AUDIT_BIM_API_KEY": TEST_API_KEY,
            "AUDIT_INPUT_DIR": str(input_dir),
        }
    )
    info["api_key"] = TEST_API_KEY
    try:
        yield info
    finally:
        _terminate(proc)


def pytest_collection_modifyitems(config, items):
    """Skipe les tests d'intégration si ``python`` introuvable."""
    if not shutil.which(sys.executable):
        skip = pytest.mark.skip(reason=f"Python introuvable : {sys.executable}")
        for item in items:
            item.add_marker(skip)
