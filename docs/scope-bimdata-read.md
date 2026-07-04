# Scope — MCP / package `bimdata-read`

Document d'architecture **figé avant tout code**. Il définit la frontière du
futur package de lecture BIMData, ce qui en sort, ce qui reste dans
`audit-bim-i3f`, l'ordre des PR et les critères de parité.

Objectif : isoler le **noyau de lecture** BIMData (API + cache + snapshot) dans
un package pur, réutilisable par les futurs MCP, **sans y embarquer** l'écriture
BIMData ni les règles métier I3F.

## 1. Principe directeur

Trois responsabilités sont aujourd'hui mêlées dans `audit_bim/extraction/` :

| Responsabilité | Nature | Destination |
|---|---|---|
| Lecture API BIMData + dénormalisation + snapshot + cache | générique | **→ `bimdata-read`** |
| Écriture BIMData (BCF, Smart Views, classifications, psets) | générique mais **hors lecture** | reste en audit-bim → plus tard **MCP BIMData Write** |
| Normalisation ArchiCAD/I3F (LongName→Name, Superficie calculée…) | **métier I3F** | reste en `audit-bim-i3f` |

Règle : `bimdata-read` ne dépend que de `bim-core` (où vit déjà `ModelSnapshot`)
et de `requests`. **Aucune** dépendance à `audit_bim` (ni `config`, ni écriture,
ni `normalizer`).

## 2. Le point dur — split lecture/écriture de `BIMDataClient`

`BIMDataClient` ([extraction/client.py](../audit_bim/extraction/client.py)) est
**mixte** : transport + méthodes de lecture `get_*` **et** écriture
(`create_bcf_full_topic` l.353, `_post` l.226 utilisé aussi directement par
`classifier/applier.py:140,192`).

Décision : **scinder par héritage**, sans casser le nom `BIMDataClient`.

- `bimdata-read` expose **`BIMDataReadClient`** : auth/session/retry, `_url`,
  `_get`, toutes les méthodes `get_*` + dénormalisation `/element/raw`.
  Aucune écriture.
- `audit-bim-i3f` garde **`BIMDataClient(BIMDataReadClient)`** qui **ajoute** le
  transport d'écriture `_post` + `create_bcf_full_topic`. Les consommateurs
  d'écriture (`bcf/builder`, `smartview/builder`, `classifier/applier`,
  `actions/*_planner`) continuent d'importer `BIMDataClient` **inchangé**.

Ainsi la façade `audit_bim.extraction.client.BIMDataClient` reste lecture+écriture
tant que le MCP Write n'est pas sorti ; seul le **noyau lecture** part.

## 3. Découplage de `config`

`client.py` importe `from .. import config` et lit `BIMDATA_BASE_URL`,
`CLOUD_ID/PROJECT_ID/MODEL_ID`, `ACCESS_TOKEN`, `API_KEY` (l.110-141).

`BIMDataReadClient` doit être **agnostique** : il reçoit `base_url` + le mode
d'auth (api_key / access_token / oauth client_credentials) en **paramètres**
explicites (ou lit ses propres variables d'env `BIMDATA_*`, sans importer
`audit_bim.config`). La façade `BIMDataClient` d'audit-bim garde le fallback sur
`config.*` et les passe à `super().__init__(...)` — le comportement actuel
(fallback `.env`) est préservé côté audit-bim.

## 4. Symboles à EXTRAIRE vers `bimdata-read`

| Symbole | Source actuelle | Note |
|---|---|---|
| `BIMDataReadClient` (partie lecture de `BIMDataClient`) | `extraction/client.py:55` | auth/session/retry, `_url`, `_get`, `get_project/model/sites/buildings/building_detail/storeys/spaces/zones/raw_elements/structure_tree` + helpers dénormalisation (`expand_pset`, `by_index`) |
| `BIMDataAuthError` | `extraction/client.py:47` | erreur d'auth (401/403) |
| `extract_snapshot(client)` | `extraction/model_data.py:21` | consomme `bim_core.ModelSnapshot` |
| `save_snapshot_to_cache` / `load_snapshot_from_cache` / `cached_extract_snapshot` + helpers (`_cache_key`, `_serialize`, `_deserialize`, `_atomic_write`, `_SNAPSHOT_FIELDS`, `_CACHE_SCHEMA_VERSION`) | `extraction/snapshot_cache.py` | cache gzip + versionné |

`ModelSnapshot` est **déjà** dans `bim-core` — `bimdata-read` l'importe, ne le
redéfinit pas.

## 5. Symboles à GARDER dans `audit-bim-i3f`

| Symbole | Raison |
|---|---|
| `BIMDataClient(BIMDataReadClient)` + `_post` + `create_bcf_full_topic` | écriture BIMData (→ futur MCP Write) ; préserve la façade |
| `normalizer.py` entier (`get_attribute`, `resolve_value`, `get_attribute_with_fallback`, `get_quantity_with_fallback`, `ATTRIBUTE_FALLBACKS`, `QUANTITY_FALLBACKS`) | **règles métier ArchiCAD/I3F** (LongName→Name, Superficie calculée) — pas une abstraction BIMData |
| Les shims `extraction/client.py`, `extraction/model_data.py`, `extraction/snapshot_cache.py` | ré-export depuis `bimdata-read` pour préserver les chemins d'import historiques |

## 6. Façade à préserver (ne doit rien casser)

Importeurs actuels de `extraction/*` (doivent continuer à fonctionner via shims) :

- `extraction.model_data.ModelSnapshot` — importé par `audit/engine`,
  `audit/rules/*`, `query/*`, `reporting/*`, `doe/*`, `actions/doe_planner`,
  `mcp/server`, `mcp/session`. (Déjà un ré-export de `bim-core`.)
- `extraction.model_data.extract_snapshot` — `cli.py`, `mcp/server.py`.
- `extraction.snapshot_cache.cached_extract_snapshot` — `mcp/server.py`.
- `extraction.client.BIMDataClient` — `actions/*_planner`, `bcf/builder`,
  `smartview/builder`, `classifier/applier`, `doe/enricher`, `cli`, `mcp/server`,
  `mcp/session`.
- `extraction.normalizer.get_attribute/resolve_value` — `audit/rules/*`, `doe/*`
  (**reste local**, non déplacé).

Outils MCP dépendant de l'extraction, à **préserver sans changement utilisateur**
([mcp/server.py](../audit_bim/mcp/server.py)) : `set_active_model`,
`extract_model_snapshot`, `verify_active_model`, `full_audit`.

## 7. Ordre PR par PR

0. **`docs/scope-bimdata-read`** (cette PR) — figer le périmètre. Aucun code.
1. **`bimdata-read` package pur** (repo/tag séparé, comme bim-core) :
   `BIMDataReadClient` + `extract_snapshot` + `snapshot_cache`, dépend de
   `bim-core` + `requests`. Tests propres du package. Tag `bimdata-read-v0.1.0`.
2. **Adoption dépendance** (PR conso, sur audit-bim-i3f) : `pyproject` +
   `[tool.uv.sources]` (tag Git) + `uv.lock` + CI/release — infra only, pas de
   shims. (Même schéma que la conso bim-core #30.)
3. **Shims façade** dans `audit_bim/extraction/*` :
   - `client.py` → `BIMDataClient(BIMDataReadClient)` + écriture locale ;
   - `model_data.py` → ré-export `ModelSnapshot` (bim-core) + `extract_snapshot`
     (bimdata-read) ;
   - `snapshot_cache.py` → ré-export bimdata-read.
   `normalizer.py` **inchangé**.
4. **Plus tard seulement** — MCP **BIMData Write** séparé : `create_bcf_full_topic`,
   Smart Views, classifications, propertysets. Hors de ce scope.

## 8. Critères de parité (gate de chaque PR)

- **Tests** : les **1000** tests unitaires + **9** d'intégration restent verts,
  sans modification (référence : tag `legacy-i3f-mcp-v1`).
- **Identité** : `audit_bim.extraction.client.BIMDataClient` reste lecture+écriture ;
  `extract_snapshot`, `cached_extract_snapshot`, `ModelSnapshot` importables aux
  mêmes chemins.
- **Aucun changement d'outil MCP** : `set_active_model`, `extract_model_snapshot`,
  `verify_active_model`, `full_audit` identiques côté utilisateur.
- **Parité fonctionnelle réelle** : le pack AVP se régénère non vide sur le modèle
  BIMData réel (250613_MN_BAT / projet I3F 2698917 / modèle 1726110) — même
  procédure que la validation AVP.
- **CI verte depuis install propre** : `bimdata-read` résolu depuis son tag Git
  public ; `uv lock --check` cohérent ; ruff `check` + `format --check` clean ;
  `pip-audit` clean.

## 9. Hors scope (à ne pas mélanger)

- Écriture BIMData (BCF, Smart Views, classifications, psets) — restera dans
  audit-bim jusqu'au **MCP BIMData Write** dédié.
- `normalizer.py` (règles ArchiCAD/I3F).
- Toute nouvelle logique métier : les PR 1–3 sont **du déplacement**, à parité.
