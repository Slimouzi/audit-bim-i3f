#!/bin/sh
# Lanceur déterministe du serveur MCP audit-bim en transport stdio.
#
# Pourquoi ce script plutôt que `zsh -lc "cd … && exec …"` dans la config
# Claude Code : un shell de **connexion** (`-l`) source .zprofile / .zlogin
# (et .zshrc en interactif). Toute sortie émise par ces fichiers (echo de
# bienvenue, `nvm`/`pyenv` bavards, bannières) part sur stdout **avant** le
# handshake JSON-RPC et **corrompt le protocole MCP stdio**. `#!/bin/sh` en
# POSIX ne source aucun profil de connexion : démarrage reproductible.
#
# On se place dans le dossier du projet pour que python-dotenv (config.py)
# charge le `.env` local (clé API + cible BIMData) sans exposer de secret
# dans la configuration Claude Code.
set -e
cd "$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
exec .venv/bin/audit-bim-mcp --transport stdio
