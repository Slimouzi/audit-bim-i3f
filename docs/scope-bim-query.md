# Scope — package `bim-query` (couche requête read-only)

Document d'architecture **figé avant tout code**. Il cartographie la couche
**requête/sélection read-only** *déjà existante* dans `audit-bim-i3f`
(`audit_bim/query/*` + `audit_bim/mcp/tools_query.py`), fixe la frontière du
futur package commun, les contrats, l'ordre des PR et les critères de parité.

**Cette PR ne modifie aucun code applicatif** — inventaire et décision seulement.

Objectif : **extraire/productiser** une couche requête existante et éprouvée en
un package réutilisable, **sans réécriture** et **sans changement observable**.
Ce n'est **pas** une première implémentation from scratch : le code métier est
déjà écrit, testé, et branché sur les contrats `bim-core`.

## 0. Décisions figées (revue CTO)

**Décision 1 — c'est une extraction, pas une création.** La couche vit déjà dans
`audit_bim/query/` (filtrage, alias de propriétés, requêtes tabulaires, presets)
et consomme déjà les contrats extraits (`bim-core`, `bimdata-read`). Le chantier
consiste à la **sortir derrière une frontière propre** et à la republier, en
gardant `audit-bim-i3f` comme façade (ré-exports), à l'identique du schéma
bim-core / bimdata-read / bim-sandbox.

**Décision 2 — read-only strict.** Query **lit** un `ModelSnapshot` / des objets
normalisés (`BimObject`) et ne fait **aucune écriture BIMData**, aucun appel
réseau, aucune mutation d'état. Frontière non négociable (cf. §4, §6).

**Décision 3 — nommage `bim-query` (à trancher, recommandation posée).**
Recommandation : **`bim-query`** plutôt que `bimdata-query`. Raison
architecturale : la couche travaille sur un **snapshot normalisé** (`ModelSnapshot`
+ `BimObject` de `bim-core`), pas sur le transport BIMData. Elle est
**source-agnostique** — le champ `source` (`"bimdata"`, …) est une simple donnée
filtrable, pas une dépendance. `bimdata-query` sur-signalerait un couplage
BIMData qui n'existe pas. `bim-query` s'aligne sur `bim-core`. **Décision finale
laissée au CTO.** (Le fichier est nommé `scope-bim-query.md` pour refléter la
recommandation ; à renommer si le CTO tranche `bimdata-query`.)

**Décision 4 — la validation A1 (écritures BCF/SmartViews réelles) ne bloque pas
cette PR.** A1 est un contrôle **write** sur projet BIMData bac-à-sable ; Query
est **read-only** et avance en parallèle.

## 1. Constat — couche read-only déjà en place

Tout le code cité ci-dessous **existe déjà** dans `audit-bim-i3f` (`master`).

| Module | Rôle | Réseau / écriture |
|---|---|---|
| `audit_bim/query/filtering.py` | prédicats + pagination objets / findings / suggestions | aucun |
| `audit_bim/query/property_aliases.py` | résolution sémantique de champs (alias multi-langue) | aucun |
| `audit_bim/query/table_query.py` | requêtes tabulaires (`BimQuery` → `BimQueryResult`) | aucun |
| `audit_bim/query/views.py` | adaptateur `ModelSnapshot` → `BimObject` (itérateur lazy) | aucun |
| `audit_bim/mcp/tools_query.py` | surface MCP (8 outils) + presets métier | délègue le spill disque au layer MCP |
| `audit_bim/mcp/selection.py` | résolution de sélection (intersection objets × findings) | aucun |

Dépendances déjà modularisées : `BimObject`/`ClassificationRef` (bim-core),
`ObjectFilter`/`FindingFilter`/`SuggestionFilter` + `DEFAULT_LIMIT`/`MAX_LIMIT`
(bim-core), `ModelSnapshot` (bim-core), `Finding`/`Severity`/`Theme`/`ErrorType`
(bim-core). Aucune réécriture de contrat nécessaire.

## 2. Inventaire de l'existant

### 2.1 Surface MCP (`audit_bim/mcp/tools_query.py`)

Huit outils `@mcp.tool()`. Les cinq premiers sont la couche requête pure ; les
trois derniers sont la couche tabulaire/presets.

| Outil | Rôle | Sortie clé |
|---|---|---|
| `filter_bim_objects` | sélection d'objets via `ObjectFilter` + intersection findings | `{items, uuids, total, next_offset, …}` |
| `show_filtered_objects_in_viewer` | instruction viewer (isolate/select/color) sur une sélection | `{ok, mode, count, uuids, viewer_instruction, …}` |
| `list_audit_findings` | filtrage de findings (aucune recompute) via `FindingFilter` | `{items, total, next_offset, …}` |
| `get_object_detail` | 1 `BimObject` + findings liés + suggestion de classification | `{object, findings, n_findings, suggestion}` |
| `list_classification_suggestions` | filtrage du store de suggestions | `{items, total, store_counts, …}` |
| `query_bim_data` | requête tabulaire sémantique (fields + alias + `Pset.Prop`) | `{columns, rows, total, warnings, …}` |
| `query_bim_preset` | requête tabulaire préconfigurée (preset métier) | idem + `{preset, preset_description}` |
| `list_query_presets` | liste des presets disponibles | `{presets:[…], total}` |

`show_filtered_objects_in_viewer` **ne crée pas de Smart View** : il produit une
instruction viewer côté client. La création de Smart View (write) reste hors
périmètre (couche Publication / actions).

### 2.2 Moteur de filtrage (`query/filtering.py`)

- `apply_object_filter(objects, f, sort_key=None) → (items, total, next_offset)`
- `apply_finding_filter(findings, f) → (items, total, next_offset)`
- `apply_suggestion_filter(store, f) → (items, total, next_offset)`
- Prédicats sans pagination réexposés : `object_matches`, `finding_matches`,
  `suggestion_matches` (consommés par les planners actions — cf. §4).
- Convention de pagination : offset/limit appliqués **après** filtrage ;
  `total` = nombre de matches avant pagination ; `next_offset = None` en fin.

### 2.3 Résolution sémantique (`query/property_aliases.py`)

Résolution `field → {value, source, matched_key}` avec familles d'alias
multi-langue (FR/EN) : acoustique (`Rw`, `AcousticRating`…), feu (`FireRating`,
`DegreReactionFeu`…), dimensions (height/width/thickness/area/volume/perimeter/
length), matériaux, fabricant, référence, tag/repère, maintenance/GMAO, n° série.
Ordre de résolution : attributs natifs → agrégats (materials/layers/
classification) → dimensions composites → quantités → propriétés Pset → fallback
dynamique. Fonctions pures, zéro I/O.

### 2.4 Requêtes tabulaires (`query/table_query.py`)

- `BimQuery(object_filter, fields, include_empty, flatten_lists, limit, offset)`
  (pydantic strict, `extra=forbid`, `limit` 1–500 défaut 100).
- `BimQueryResult(columns, rows, total, next_offset, warnings)`,
  `BimQueryRow(uuid, cells{value,source,matched_key}, values)`.
- `query_bim_table(snapshot, query) → BimQueryResult` : filtre → projette
  chaque objet via `resolve_requested_field` → filtre lignes vides (si
  `include_empty=False`) → pagine → émet des warnings qualité (>80 % de valeurs
  manquantes sur un champ sémantique, champ inconnu).
- Champs connus (~33) : identité, classification, spatial, materials/layers,
  flags, dimensions, sémantique métier.

### 2.5 Adaptateur snapshot → objets (`query/views.py`)

- `iter_bim_objects(snapshot, include_spatial=False) → Iterator[BimObject]`
  (exclut par défaut Site/Building/Storey/Space/Zone).
- `bim_object_from_element(element, snapshot) → BimObject` : aplatit les Psets
  (`"Pset.Prop": value`), extrait BaseQuantities, booléens `*Common`,
  classifications, contexte spatial (storey/space/zone), materials/layers dédupés.
- Index spatial construit et **mis en cache sur le snapshot** via `setattr`
  (`_SPATIAL_INDEX_ATTR`) — seule mutation, un cache d'index dérivé, jamais les
  données éléments. **Point de parité à surveiller** lors de l'extraction.

### 2.6 Presets métier (`tools_query.py`, dict `QUERY_PRESETS`)

Trois presets prioritaires **déjà implémentés** :

| Preset | Filtre | Champs (extrait) |
|---|---|---|
| `doors_acoustic_dimensions` | `IfcDoor`, `IfcDoorStandardCase` | materials, acoustic_performance, height/width/thickness, fire_rating, storey, space |
| `walls_fire_acoustic` | 4 types de murs (dont `IfcCurtainWall`) | materials, fire_rating, acoustic_performance, thickness, is_external, load_bearing, storey |
| `equipment_maintenance` | ~45 types CVC/élec/plomberie | manufacturer, reference, maintenance_id, serial_number, tag, space, zone |

Presets prioritaires **à venir** (non codés, hors scope de cette PR, notés pour
la roadmap) : I3F / CCH (nomenclatures métier dédiées).

### 2.7 Overflow disque (`audit_bim/mcp/payloads.py::maybe_dump_to_disk`)

Déclenché si payload > 256 KB **ou** `output_path` explicite : écrit le résultat
complet dans `AUDIT_OUTPUT_DIR` (validé par `safe_export_path`, désormais
`bim-sandbox`) et renvoie un payload compact (preview items/uuids + métadonnées
`items_path`, `*_truncated`). **Cette mécanique appartient à la couche MCP/
sandbox**, pas au cœur requête : à laisser côté façade (cf. §5).

## 3. Contrats (entrées / sorties figées)

- **Entrée données** : `ModelSnapshot` (bim-core) — `elements`, hiérarchie
  spatiale (`sites/buildings/storeys/spaces/zones`), `structure_tree`.
- **Objet normalisé** : `BimObject` (bim-core) — identité, spatial, flags,
  layers/materials, classifications, `properties` (dict `Pset.Prop`),
  `base_quantities`, `source`.
- **Filtres** (bim-core, pydantic) : `ObjectFilter` (~24 champs — uuids,
  ifc_types, storey/zone/space × name/uuid, is_external, load_bearing,
  classification, has/missing_property, has/missing_quantity, name_contains/
  name_regex, layer/material_contains, source), `FindingFilter` (themes,
  severities, severity_min, error_types, ifc_types, element_uuids,
  require_element_uuid), `SuggestionFilter`.
- **Alias propriétés** : familles multi-langue résolues vers
  `{value, source, matched_key}` (traçabilité).
- **Pagination** : `limit` (défaut `DEFAULT_LIMIT`=100, max `MAX_LIMIT`=500),
  `offset` ≥0, `next_offset` cursor.
- **Résultats tabulaires** : `BimQuery` / `BimQueryRow` / `BimQueryResult`
  (colonnes ordonnées, cells traçables, warnings qualité).

Le vocabulaire (noms de champs, alias, presets, sévérités) est **le contrat**.
Toute évolution se fait des deux côtés (façade + package).

## 4. Frontière du package `bim-query`

**Dans le package** (cœur requête pur, testable offline sur snapshot fixture) :
`filtering.py`, `property_aliases.py`, `table_query.py`, `views.py`, et le
registre `QUERY_PRESETS` (données de presets + résolution).

**Hors package** (restent côté `audit-bim-i3f` / autres couches) :
- surface MCP `@mcp.tool()` et l'état de session (`_State.snapshot/result/store`) ;
- overflow disque / sandbox (`maybe_dump_to_disk`, `safe_export_path` → relève de
  `bim-sandbox`) ;
- `get_object_detail`/`list_classification_suggestions` **couplés à l'audit** :
  la partie findings/suggestions dépend de `AuditResult` et du
  `ClassificationSuggestionStore` (couche audit/classifier) — le filtrage pur
  (`apply_finding_filter`, `apply_suggestion_filter`) va dans le package, mais la
  **source** des findings/suggestions reste côté audit.

**Consommateurs internes à préserver** (import des prédicats purs, read-only) :
`mcp/selection.py`, `actions/smartview_planner.py` (`finding_matches`),
`actions/bcf_planner.py` (`finding_matches`),
`actions/classification_planner.py` (`suggestion_matches`). Ces call-sites
doivent continuer à importer les mêmes symboles via la façade — **zéro
réécriture**.

## 5. Ordre des PR (à valider)

Aligné sur le schéma éprouvé bim-core / bimdata-read / bim-sandbox :

1. **PR scope (celle-ci)** — doc figé, aucun code applicatif.
2. **Package pur `bim-query` + tag `bim-query-v0.1.0`** — extraction du cœur
   (`filtering`, `property_aliases`, `table_query`, `views`, presets) + suite de
   tests unitaires portée telle quelle (fixtures snapshot). Dépend de `bim-core`.
   Aucun couplage MCP / sandbox / réseau.
3. **PR adoption (infra-only) dans `audit-bim-i3f`** — ajout de la dépendance
   (git tag + `[tool.uv.sources]`), wiring CI/preinstall. Aucun changement de
   comportement.
4. **PR shim** — `audit_bim/query/*` deviennent des ré-exports fins du package ;
   tests d'identité (`X is bim_query.X`) garantissant que les call-sites
   (selection, planners) référencent les **mêmes objets**.

Suppression de l'ancien code **seulement après preuve** : tests de parité verts +
résultats déterministes sur fixture snapshot stable.

## 6. Non-objectifs

- Aucune écriture BIMData (BCF apply, Smart Views apply, classifications, DOE,
  Psets) — couche Publication / Write-actions, chantiers ultérieurs.
- Aucun client transport BIMData ni appel réseau (relève de `bimdata-read`).
- Aucune mutation d'état de session ni du `ModelSnapshot` (hors cache d'index
  dérivé, préservé à l'identique).
- Pas d'ajout des presets I3F/CCH dans ce chantier (roadmap ultérieure).
- Pas d'unification/renommage des contrats de filtres (restent tels quels).

## 7. Critères de parité

- **Tests unitaires existants portés tels quels** et verts dans le package :
  `test_query_filtering.py`, `test_bim_table_query.py`, `test_property_aliases.py`,
  `test_domain_filters.py`, plus les tests d'intégration MCP côté façade
  (`test_mcp_query_bim_data.py`, `test_mcp_filter_tools.py`).
- **Fixture snapshot stable** : jeux `snapshot_mixed`, `snapshot_doors_walls`
  reproductibles, résultats **déterministes** (mêmes lignes, même ordre, mêmes
  warnings, mêmes `next_offset`).
- **Tests d'identité de façade** : `audit_bim.query.<f> is bim_query.<f>` pour les
  prédicats et fonctions publiques (isinstance-safe pour les consommateurs).
- **Zéro changement observable** côté outils MCP : payloads identiques (colonnes,
  cells, totals, presets, warnings) avant/après extraction.
- **Read-only prouvé** : garde CI (grep) interdisant tout appel réseau/écriture
  dans le package `bim-query`.

## 8. Décision en attente (CTO)

- **Nommage définitif** : `bim-query` (recommandé) vs `bimdata-query`.
- Confirmation de l'ordre des PR §5 et de la frontière §4 (notamment le
  traitement findings/suggestions couplés audit).
