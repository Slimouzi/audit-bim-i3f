"""Intégration audit-bim-i3f dans LangChain (via langchain-mcp-adapters).

Pré-requis :
    pip install langchain-mcp-adapters langchain-openai langgraph
"""
import asyncio

from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.prebuilt import create_react_agent


async def main():
    client = MultiServerMCPClient(
        {
            "audit-bim-i3f": {
                "command": "python",
                "args": ["-m", "audit_bim.mcp"],
                "cwd": "/Users/stani/code/MCP/audit-bim-i3f",
                "transport": "stdio",
            }
        }
    )
    tools = await client.get_tools()
    agent = create_react_agent("openai:gpt-4o", tools)

    response = await agent.ainvoke(
        {
            "messages": [
                (
                    "user",
                    "Lance un audit complet de la maquette I3F en phase AVP "
                    "et résume les findings par thème.",
                )
            ]
        }
    )
    print(response["messages"][-1].content)


if __name__ == "__main__":
    asyncio.run(main())
