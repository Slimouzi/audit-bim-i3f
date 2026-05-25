# Claude Desktop — branchement local du MCP

Procédure pour utiliser `audit-bim-i3f` depuis **Claude Desktop** en mode
**stdio**. C'est le mode prévu pour un AMO BIM en interactif : un seul
client (Claude), un canal IPC local, pas d'exposition réseau.

## Pré-requis

```bash
cd /Users/stani/code/MCP/audit-bim-i3f
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -e ".[test,ocr]"
.venv/bin/audit-bim-mcp --help   # vérification
```

L'extra `[ocr]` ajoute `pytesseract`, `pdf2image`, `Pillow` pour les
DOE PDF scannés. Si tu n'en as pas besoin :

```bash
.venv/bin/pip install -e ".[test]"
```

Le binaire `tesseract` (et `poppler` pour `pdf2image`) doivent être
installés à part :

```bash
brew install tesseract poppler          # macOS
sudo apt install tesseract-ocr poppler-utils   # Linux
```

## Deux clés d'API — à ne pas confondre

| Variable | Pour quoi ? | Quand la définir ? |
|---|---|---|
| `BIMDATA_API_KEY` | Auth BIMData (le serveur appelle `api.bimdata.io`) | **Toujours**, sauf si tu utilises `BIMDATA_CLIENT_ID` + `BIMDATA_CLIENT_SECRET`. C'est *ta* clé personnelle BIMData, générée depuis le cloud à auditer. |
| `AUDIT_BIM_API_KEY` | Auth applicative du **serveur MCP** (header `X-API-Key`) | **Jamais** en stdio local. Sert uniquement quand le MCP est exposé en HTTP/SSE derrière un reverse-proxy. |

En stdio (Claude Desktop), le canal IPC est implicitement de confiance —
l'auth applicative MCP n'a pas de sens, seule `BIMDATA_API_KEY` compte.

## Politique d'écriture BIMData

En stdio, `AUDIT_BIM_ALLOW_WRITES` vaut **`true` par défaut** : les tools
mutatifs (`apply_classifications`, `doe_enrich_model`, `create_bcf_topics`,
`create_smart_views`, `full_audit` avec push) peuvent toucher BIMData.

**Commence toujours en `dry_run=true`** pour valider le payload avant
de pousser réellement. Exemple :

```text
"Crée les BCF topics en dry-run."   # dry_run=true par défaut
"Maintenant pousse-les réellement."  # dry_run=false explicite
```

Pour interdire toute écriture côté serveur, même en stdio :

```bash
export AUDIT_BIM_ALLOW_WRITES=false
```

## Configuration Claude Desktop (macOS)

Édite le fichier :

```
~/Library/Application Support/Claude/claude_desktop_config.json
```

### Variante 1 — minimale (l'env BIMData est dans `.env` du repo)

```json
{
  "mcpServers": {
    "audit-bim-i3f": {
      "command": "/Users/stani/code/MCP/audit-bim-i3f/.venv/bin/audit-bim-mcp",
      "args": ["--transport", "stdio"],
      "cwd": "/Users/stani/code/MCP/audit-bim-i3f"
    }
  }
}
```

`cwd` est important — le serveur lit `.env` à partir du répertoire
courant. Le `.env` du repo (ignoré par git) doit contenir au minimum :

```dotenv
BIMDATA_API_KEY=…
BIMDATA_CLOUD_ID=…
BIMDATA_PROJECT_ID=…
BIMDATA_MODEL_ID=…
I3F_CCH_PDF=/chemin/absolu/vers/CCH_I3F_V3.6.pdf
I3F_DATA_SPEC_XLSX=/chemin/absolu/vers/annexe_specifications.xlsx
I3F_NAMING_SPEC_XLSX=/chemin/absolu/vers/annexe_nommage.xlsx
```

### Variante 2 — env inline (sans `.env` côté repo)

Pratique pour tester plusieurs profils sans toucher au `.env` :

```json
{
  "mcpServers": {
    "audit-bim-i3f": {
      "command": "/Users/stani/code/MCP/audit-bim-i3f/.venv/bin/audit-bim-mcp",
      "args": ["--transport", "stdio"],
      "cwd": "/Users/stani/code/MCP/audit-bim-i3f",
      "env": {
        "BIMDATA_API_KEY": "REPLACE_ME",
        "BIMDATA_CLOUD_ID": "REPLACE_ME",
        "BIMDATA_PROJECT_ID": "REPLACE_ME",
        "BIMDATA_MODEL_ID": "REPLACE_ME",
        "AUDIT_OUTPUT_DIR": "/Users/stani/code/MCP/audit-bim-i3f/out"
      }
    }
  }
}
```

`AUDIT_OUTPUT_DIR` confine les exports (xlsx, docx, json, cache snapshot)
au dossier indiqué — sandbox d'écriture par défaut.

Après modification, **quitte et relance Claude Desktop** complètement
(menu Claude → Quit, pas seulement fermer la fenêtre) pour qu'il
recharge la config.

## Smoke test dans Claude Desktop

À taper dans une conversation Claude, dans l'ordre :

1. « **Liste les outils MCP audit-bim-i3f disponibles.** »
   Doit énumérer une vingtaine de tools (`project_context_questions`,
   `extract_model_snapshot`, `full_audit`, etc.).

2. « **Utilise audit-bim-i3f pour afficher les questions de contexte projet.** »
   Appelle `project_context_questions`. Renvoie les champs manquants
   pour cadrer l'audit (phase, classification, CCH, etc.).

3. « **Configure la maquette depuis les variables d'environnement,
   phase PRO, puis extrait le snapshot.** »
   Enchaîne `set_active_model` (sans `access_token` — c'est l'env
   serveur qui fait foi) puis `extract_model_snapshot`. Renvoie un
   résumé du modèle BIMData.

4. « **Parse les exigences maître d'ouvrage puis lance un audit sans
   publication BIMData.** »
   Enchaîne `parse_owner_requirements` puis `full_audit` avec
   `push_mode="none"`. Aucun side-effect BIMData.

5. « **Génère le rapport Word et l'annexe Excel.** »
   `generate_word_report` + `generate_xlsx_annex`. Chemins sandboxés
   sous `AUDIT_OUTPUT_DIR`.

6. « **Propose les classifications manquantes sans les appliquer.** »
   `suggest_classifications` puis `apply_suggested_classifications`
   avec `dry_run=true`. Aperçu sans aucune écriture BIMData.

7. « **Crée les BCF topics en dry-run.** »
   `create_bcf_topics` avec `dry_run=true`. Payloads JSON visibles, pas
   de POST.

À ce stade, si tout passe, tu peux refaire les étapes 6 et 7 avec
`dry_run=false` pour pousser réellement.

## Dépannage

| Symptôme | Cause probable | Correctif |
|---|---|---|
| Claude ne voit pas le serveur MCP | Config pas rechargée | **Quitter** Claude Desktop (menu Claude → Quit), pas juste fermer la fenêtre, puis relancer. |
| `command not found: audit-bim-mcp` | Chemin venv incorrect dans la config | Vérifier le chemin absolu `~/code/MCP/audit-bim-i3f/.venv/bin/audit-bim-mcp` (existe + est exécutable). |
| Erreur d'auth BIMData (401/403) | `BIMDATA_API_KEY` manquante / périmée / mauvais scope | Régénérer la clé depuis l'interface BIMData du cloud cible. Vérifier `BIMDATA_CLOUD_ID` / `..._PROJECT_ID` / `..._MODEL_ID`. |
| `Aucune adresse exploitable` | `I3F_CCH_PDF` / `I3F_DATA_SPEC_XLSX` / `I3F_NAMING_SPEC_XLSX` non définis ou chemins invalides | Mettre des chemins **absolus** existants dans `.env` ou env inline. |
| `OCR Tesseract not found` | Binaire `tesseract` manquant | `brew install tesseract poppler` (macOS) ou équivalent Linux. |
| Écritures BIMData involontaires | Tool mutatif appelé avec `dry_run=false` par mégarde | Toujours valider en `dry_run=true` d'abord. Pour bloquer côté serveur : `AUDIT_BIM_ALLOW_WRITES=false` dans l'env. |
| `AccessTokenParamDisabledError` | Tool appelé avec `access_token=…` sur transport réseau | En stdio ce ne devrait pas arriver. Si en HTTP, utiliser `BIMDATA_API_KEY` côté serveur. |

## Pourquoi pas `AUDIT_BIM_API_KEY` en stdio ?

`AUDIT_BIM_API_KEY` est l'auth **du serveur MCP lui-même** (header
`X-API-Key` vérifié à l'init MCP) — utile uniquement pour les
transports HTTP/SSE exposés derrière un reverse-proxy.

En stdio :
- Le serveur est un sous-process lancé par Claude Desktop.
- Le canal de communication (pipes stdin/stdout) est confiné au système
  local et n'est pas atteignable depuis le réseau.
- Personne d'autre que Claude Desktop ne peut s'y connecter.

Définir `AUDIT_BIM_API_KEY` en stdio ne nuit pas mais n'apporte aucune
garantie supplémentaire. C'est inutile.

Le durcissement HTTP reste intact : si tu lances `audit-bim-mcp
--transport http` plus tard, toutes les gardes décrites dans
[SECURITY.md](../SECURITY.md) s'appliquent.
