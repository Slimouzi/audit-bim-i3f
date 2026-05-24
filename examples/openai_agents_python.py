"""Intégration audit-bim-i3f dans OpenAI Agents SDK.

Pré-requis :
    pip install openai-agents

Le serveur MCP est démarré en sous-processus stdio par l'agent. Il faut
que les variables d'env BIMDATA_* + I3F_* soient définies dans
l'environnement parent (ou un .env chargé).
"""
import asyncio

from agents import Agent, Runner
from agents.mcp import MCPServerStdio


async def main():
    async with MCPServerStdio(
        params={
            "command": "python",
            "args": ["-m", "audit_bim.mcp"],
            "cwd": "/Users/stani/code/MCP/audit-bim-i3f",
        }
    ) as mcp_server:
        agent = Agent(
            name="AMO BIM I3F",
            model="gpt-4o",
            instructions=(
                "Tu es un AMO BIM senior spécialisé I3F. Commence par "
                "appeler project_context_questions pour cadrer l'audit, "
                "puis utilise les tools MCP pour produire les livrables."
            ),
            mcp_servers=[mcp_server],
        )
        result = await Runner.run(
            agent,
            "Audite la maquette I3F en phase AVP, génère le Word et le XLSX, "
            "et liste-moi les 5 anomalies les plus graves.",
        )
        print(result.final_output)


if __name__ == "__main__":
    asyncio.run(main())
