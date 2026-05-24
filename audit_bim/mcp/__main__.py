"""Permet ``python -m audit_bim.mcp [--transport stdio|http|sse|streamable-http] [--host ...] [--port ...]``.

Transports supportés par FastMCP 3.x :

- ``stdio`` (défaut) — utilisé par les clients MCP locaux (Claude Desktop,
  LangChain MCP adapter, OpenAI Agents SDK, CrewAI MCP tool).
- ``http`` / ``streamable-http`` — endpoint HTTP RPC pour clients Node.js,
  apps métier BIM, intégrations custom.
- ``sse`` — Server-Sent Events pour clients web temps réel.
"""

from __future__ import annotations

import argparse
import sys

from .server import mcp


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
        help="Hôte d'écoute (transports http/sse).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Port d'écoute (transports http/sse).",
    )
    args = parser.parse_args()

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
