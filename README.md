# Audit BIM I3F — MCP server

MCP qui automatise l'**audit de conformité** d'une maquette IFC hébergée sur
[BIMData.io](https://bimdata.io) au **Cahier des Charges BIM I3F** (CCH V3.x).
Pensé pour un usage AMO BIM : lecture des exigences du maître d'ouvrage,
comparaison avec la maquette, génération d'un rapport Word + d'une annexe
Excel par type d'erreur, et création de Smart Views BIMData (1 par thème).

## Pourquoi ce projet

Le CCH BIM I3F décrit, dans un **Cahier des annexes** (PDF) et deux annexes
xlsx (« Spécification des données » et « Nommage IFC »), l'ensemble des
attendus du maître d'ouvrage pour chaque phase BIM (APS → DOE → GESTION).
Vérifier manuellement la conformité d'une maquette par rapport à ces
exigences est long et source d'erreurs.

Ce MCP transforme cet audit en **5 agents** orchestrés par Claude :

| Agent | Rôle | Tools MCP |
|---|---|---|
| Requirements Parser | Lit les 3 documents MOA → catalogue d'exigences | `set_owner_documents`, `parse_owner_requirements`, `get_catalog_properties` |
| Model Extractor | Tire la maquette IFC depuis BIMData (auth OAuth2 ou API Key) | `set_active_model`, `extract_model_snapshot` |
| Audit Engine | Joue les règles (nommage, propriétés, classifications, hiérarchie) | `run_audit_tool`, `query_findings` |
| Reporter | Produit Word d'audit + annexe XLSX | `generate_word_report`, `generate_xlsx_annex` |
| Smart View Builder | Crée 1 Smart View BIMData par thème en erreur | `create_smart_views` |
| Orchestrateur | Chaîne complète en un appel | `full_audit` |

Un prompt MCP `amo_bim_i3f` charge la persona « AMO BIM senior I3F » dans
Claude (vocabulaire CCH, format de signalement, chain-of-thought).

## Prérequis

- Python 3.10+
- Compte BIMData avec une application configurée (API Key ou OAuth2)
- Les 3 documents du cahier des charges du maître d'ouvrage (PDF + 2 xlsx)

## Installation

```bash
cd /Users/stani/code/MCP/audit-bim-i3f
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
```

## Configuration

Copier `.env.example` en `.env` et renseigner :

```dotenv
# Auth BIMData — un des trois modes
BIMDATA_API_KEY=…
# ou
BIMDATA_CLIENT_ID=…
BIMDATA_CLIENT_SECRET=…

# Cible par défaut (surchargeable runtime)
BIMDATA_CLOUD_ID=…
BIMDATA_PROJECT_ID=…
BIMDATA_MODEL_ID=…

# Documents MOA (chemins absolus)
I3F_CCH_PDF=/Users/stani/code/MCP/Documents maître d'ouvrage/Cahier des annexes CCH Bim I3F V3.6 - Juil 24.pdf
I3F_DATA_SPEC_XLSX=…/Annexe Spécification des données I3F simplifiée - CCH 2021 V3.7 TDB.xlsx
I3F_NAMING_SPEC_XLSX=…/Annexe Nommage IFC 3F CCH 2021 V3.6 SHAB SU.xlsx
```

## Lancer le serveur MCP

```bash
python -m audit_bim.mcp
```

### Intégration Claude Desktop

Ajouter à `~/Library/Application Support/Claude/claude_desktop_config.json` :

```json
{
  "mcpServers": {
    "audit-bim-i3f": {
      "command": "python",
      "args": ["-m", "audit_bim.mcp"],
      "cwd": "/Users/stani/code/MCP/audit-bim-i3f"
    }
  }
}
```

## Utilisation en CLI (sans Claude)

```bash
audit-bim --phase PRO
# ou avec une cible explicite
audit-bim --cloud-id 1234 --project-id 5678 --model-id 9012 --phase DCE
# push réel des Smart Views (sinon dry-run)
audit-bim --push-smart-views
```

## Livrables produits

Dans `AUDIT_OUTPUT_DIR` (`./out` par défaut) :

- `audit_<projet>_<phase>_<date>.docx` — rapport principal (résumé exécutif,
  graphes par thème, détail des anomalies, recommandations)
- `audit_<projet>_<phase>_<date>_annexes.xlsx` — annexe détaillée :
  - onglet *Synthèse*
  - onglet *Findings (tous)*
  - 1 onglet par type d'erreur (classification manquante, nommage hors liste,
    propriété manquante, quantité manquante, hiérarchie spatiale, etc.)
  - onglet *Référentiel I3F* (listes de valeurs du CCH)
- `audit_<projet>_<phase>_<date>_findings.json` — sortie machine
- `audit_<projet>_<phase>_<date>_smart_views.json` — payloads des Smart Views

## Couverture des règles d'audit

| Thème | Règles |
|---|---|
| Hiérarchie spatiale | présence Site/Building/Storey/Space, géoréférencement |
| Nommage Site / Bâtiment / Étage | pattern I3F (`XXXXL`, `XXXXL-A`), liste fermée des étages |
| Nommage Zone | pattern `XXXXL-YYYY` (logement), liste des `ObjectType` admis |
| Nommage Pièce | liste fermée I3F + tolérance suffixes numériques (CHAMBRE 01) |
| Propriété manquante | Psets / attributs requis à la phase (depuis l'annexe Données) |
| Classification IFC | présence + complétude (code + source) |
| Quantités | NetFloorArea / SHAB / SU sur IfcSpace |

## Smart Views BIMData

Pour chaque thème en erreur, le builder produit un payload :

```json
{
  "name": "I3F Audit — Nommage Pièce",
  "description": "...",
  "model_uuid": "<model_id>",
  "elements": ["<uuid1>", "<uuid2>", "..."],
  "color": "#70AD47"
}
```

Mode `dry_run=True` par défaut (visualiser les payloads avant push). La route
est `POST /cloud/{cloud_id}/project/{project_id}{BIMDATA_SMARTVIEW_PATH}` —
`BIMDATA_SMARTVIEW_PATH` est ajustable dans `.env` si la convention diffère
sur ton tenant.

## Architecture

```
audit_bim/
├── config.py                 # .env → variables
├── cli.py                    # CLI `audit-bim`
├── requirements/             # Parseurs des documents MOA
│   ├── models.py             # Pydantic : PropertySpec, NamingRule, etc.
│   ├── data_spec_parser.py   # Annexe Spécifications xlsx
│   ├── naming_spec_parser.py # Annexe Nommage xlsx
│   ├── pdf_parser.py         # Cahier des annexes PDF
│   └── catalog.py            # Fusion des 3 sources
├── extraction/               # BIMData API
│   ├── client.py             # OAuth2 / API Key / Bearer
│   ├── model_data.py         # ModelSnapshot
│   └── normalizer.py         # Pset / attribut helpers
├── audit/                    # Moteur de règles
│   ├── findings.py           # Finding + Severity + Theme + ErrorType
│   ├── engine.py             # AuditResult + run_audit
│   └── rules/
│       ├── naming.py
│       ├── properties.py
│       ├── classifications.py
│       ├── spatial.py
│       └── lists.py
├── reporting/                # Livrables
│   ├── word_report.py        # python-docx + matplotlib
│   ├── xlsx_annex.py         # xlsxwriter
│   └── theming.py            # palette / styles I3F
├── smartview/builder.py      # Payloads Smart Views BIMData
└── mcp/
    ├── server.py             # FastMCP + 10 tools
    └── prompts.py            # Persona AMO BIM I3F
```

## Auth — ordre de précédence

1. `access_token` passé à `set_active_model(..., access_token=...)` ;
2. `BIMDATA_API_KEY` (`Authorization: ApiKey …`) ;
3. OAuth2 `client_credentials` via `BIMDATA_CLIENT_ID` + `BIMDATA_CLIENT_SECRET`.

Tous les appels API BIMData passent par un seul `BIMDataClient` qui injecte
le header `Authorization`.
