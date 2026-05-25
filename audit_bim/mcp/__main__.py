"""Permet ``python -m audit_bim.mcp [--transport ...] [--host ...] [--port ...]``.

Transports supportés par FastMCP 3.x :

- ``stdio`` (défaut) — utilisé par les clients MCP locaux (Claude Desktop,
  LangChain MCP adapter, OpenAI Agents SDK, CrewAI MCP tool).
- ``http`` / ``streamable-http`` — endpoint HTTP RPC pour clients Node.js,
  apps métier BIM, intégrations custom.
- ``sse`` — Server-Sent Events pour clients web temps réel.

Pour les transports réseau, on applique des garde-fous au démarrage
(cf. :func:`audit_bim.mcp.security.assert_startup_config`) :

- refus de démarrer si ``AUDIT_BIM_REQUIRE_API_KEY=true``
  (ou ``AUDIT_BIM_ENV=production``) sans ``AUDIT_BIM_API_KEY``,
- refus de bind ``0.0.0.0`` hors mode production explicite.
"""

from __future__ import annotations

import argparse
import logging
import sys

from .security import assert_startup_config, set_runtime_transport
from .server import mcp

logger = logging.getLogger("audit_bim.mcp")


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="python -m audit_bim.mcp",
        description="Serveur MCP audit-bim-i3f — multi-transports.",
    )
    parser.add_argument(
        "--transport",
        default="stdio",
        choices=("stdio", "http", "sse", "streamable-http"),
        help=(
            "Transport MCP. 'stdio' pour clients locaux (Claude Desktop, "
            "LangChain, CrewAI). 'http'/'streamable-http' pour Node.js et "
            "apps métier. 'sse' pour temps réel."
        ),
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help=("Hôte d'écoute (transports http/sse). 0.0.0.0 refusé sans AUDIT_BIM_ENV=production."),
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Port d'écoute (transports http/sse).",
    )
    args = parser.parse_args()

    # Mémorise le transport AVANT le check : ``assert_startup_config``
    # logge ses warnings via :func:`is_write_allowed` qui dépend du
    # transport runtime.
    set_runtime_transport(args.transport)

    # Fail-fast avant tout bind socket.
    try:
        assert_startup_config(transport=args.transport, host=args.host)
    except RuntimeError as exc:
        print(f"audit-bim-i3f MCP — refus de démarrer : {exc}", file=sys.stderr)
        return 2

    kwargs: dict = {}
    if args.transport in ("http", "sse", "streamable-http"):
        kwargs["host"] = args.host
        kwargs["port"] = args.port
        print(
            f"audit-bim-i3f MCP — transport={args.transport} sur http://{args.host}:{args.port}",
            file=sys.stderr,
        )

    mcp.run(transport=args.transport, **kwargs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
