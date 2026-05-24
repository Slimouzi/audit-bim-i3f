# Exemples d'intégration

Snippets prêts à l'emploi pour intégrer le MCP `audit-bim-i3f` depuis
différents environnements.

| Fichier | Cible | Transport |
|---|---|---|
| `openai_agents_python.py` | OpenAI Agents SDK (Python) | stdio |
| `langchain_python.py` | LangChain (Python) | stdio |
| `crewai_python.py` | CrewAI (Python) | stdio |
| `nodejs_stdio.ts` | Node.js / TypeScript | stdio |
| `nodejs_http.ts` | Node.js / TypeScript | HTTP |
| `python_direct.py` | Script Python direct (pas de MCP) | n/a — import lib |

Pour Claude Desktop, voir `../claude_desktop_config.example.json` (à copier
dans `~/Library/Application Support/Claude/claude_desktop_config.json`).

Chaque exemple suppose que :
- les variables d'env BIMData (`BIMDATA_API_KEY` ou OAuth2) sont définies,
- les chemins documents I3F sont dans `.env` (ou passés explicitement),
- `pip install -e .` ou équivalent a été exécuté dans le repo.

Pour les exemples LLM, fournir aussi la clé API du provider
(`OPENAI_API_KEY`, etc.).
