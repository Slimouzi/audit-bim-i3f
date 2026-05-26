# Changelog

Toutes les évolutions notables de ce projet sont consignées dans ce fichier.

Format basé sur [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/), versioning
[SemVer](https://semver.org/lang/fr/).

## [Unreleased]

### Changed

- **Distribution** : abandon de la publication PyPI. Le workflow Release
  produit désormais uniquement les artefacts `sdist` + `wheel` attachés à
  la GitHub Release. Installation via téléchargement direct ou
  `pip install https://github.com/Slimouzi/audit-bim-i3f/releases/download/<tag>/<file>.whl`.
  Le job `publish-pypi` est supprimé du workflow ; `create-release`
  dépend désormais directement de `build`.

## [0.2.1] — 2026-05-26

### Fixed

- Corrige la release **0.2.0** incomplète : `uv.lock` n'était pas synchronisé
  avec `pyproject.toml` (bloqué à `audit-bim-i3f v0.1.0`), ce qui faisait
  échouer le workflow Release sur `uv lock --check` **avant** les étapes
  build sdist/wheel + publication PyPI. Conséquences sur 0.2.0 :
  - Aucun asset attaché à la release GitHub.
  - Aucune publication PyPI.
- Pas de changement fonctionnel par rapport à 0.2.0 — uniquement une
  resynchronisation de `uv.lock` (`audit-bim-i3f 0.1.0 → 0.2.1`) pour
  débloquer la pipeline de release. Voir le détail des changements
  fonctionnels dans [0.2.0] ci-dessous.

### Notes

- Le tag `v0.2.0` reste en place comme jalon de référence ; il n'est pas
  déplacé. **La release installable est `v0.2.1`**.
- À l'avenir, le bump de version doit être suivi de `uv lock` dans le
  même commit pour éviter ce désynchronisation.

## [0.2.0] — 2026-05-26

Refonte architecturale autour du pattern **`prepare → validate → apply`** :
aucune écriture BIMData sans plan scellé SHA-256 + `confirm=True` explicite.

### Architecture

- **Nouvelle couche `domain/`** — modèles stables indépendants des sources :
  `BimObject` (Pydantic v2 frozen), `ObjectFilter` / `FindingFilter` /
  `SuggestionFilter` déclaratifs, `WritePlan` + `ActionResult`.
- **Moteur `query/`** — adaptateur lazy `ModelSnapshot → BimObject` (cache
  index spatial via `structure_tree`) + 3 fonctions pures de filtrage
  (`apply_object_filter` / `apply_finding_filter` / `apply_suggestion_filter`).
- **Couche `actions/`** — 4 planners : BCF Topics, Smart Views,
  Classifications, DOE Enrichment. Chacun expose `prepare_X` (scelle un
  `WritePlan`) et `apply_X` (exécute après validation).
- **`ClassificationSuggestionStore`** indexé par UUID avec statuts
  `proposed/accepted/rejected/applied`, JSON roundtrip explicite,
  préservation des statuts non-`proposed` entre re-runs du suggester.
- **Modularisation `mcp/server.py`** — 1668 → 230 lignes. Nouveaux
  modules : `deprecation.py`, `payloads.py`, `tools_query.py`,
  `tools_actions.py`, `tools_legacy.py`, `aliases.py`.

### Sécurité

- **Pattern prepare/apply** — tous les `apply_*` refusent `confirm=False`
  (retour `{"refused": True, ...}` sans toucher BIMData), valident
  l'intégrité SHA-256 du plan, valident la cible BIMData courante.
- **Journal d'écriture** (`audit_bim/security/write_journal.py`) — JSONL
  append-only thread-safe sous `AUDIT_OUTPUT_DIR/write_log/journal.jsonl`,
  consultable via le tool `audit_trail`.
- **Redaction centralisée des secrets** (`audit_bim/security/redaction.py`)
  — 11 patterns scrubés (Bearer, Token, access_token, refresh_token,
  id_token, Authorization, api_key, apikey, BIMDATA_API_KEY,
  client_secret, password), appliquée systématiquement dans
  `ActionResult.errors` et `WriteJournal.extra`.
- **Sandbox renforcée** — `safe_export_read_path` refuse les chemins
  absolus hors `AUDIT_OUTPUT_DIR` + les `..` ; `load_plan` l'utilise
  systématiquement.
- **Statuts `APPLIED` précis** — sur partial failure côté API, seuls les
  UUIDs effectivement liés passent en `APPLIED` ; les autres conservent
  leur statut pour rerun ciblé (`apply_classifications` expose désormais
  `linked_uuids` / `failed_uuids`).

### Tools MCP (40 → 46)

**13 nouveaux tools actifs** :
- Filtrage : `filter_bim_objects`, `list_audit_findings`,
  `get_object_detail`, `list_classification_suggestions`.
- Pattern prepare/apply : `prepare_bcf_topics` / `apply_bcf_topics`,
  `prepare_smart_views_plan` / `apply_smart_views_plan`,
  `prepare_classification_update_plan` / `apply_classification_update_plan`,
  `prepare_doe_enrichment_plan` / `apply_doe_enrichment_plan`.
- DOE pur : `extract_doe_records`, `match_doe_to_ifc`.
- Workflow : `update_suggestion_status`, `list_write_plans`, `audit_trail`.

**8 aliases métier** (re-dispatch strict) :
`prepare_bcf_from_findings` / `apply_bcf_plan`,
`prepare_smartviews_from_findings` / `apply_smartviews_plan`,
`prepare_classification_corrections` / `apply_classification_corrections`,
`prepare_doe_enrichment_from_file` / `apply_doe_enrichment`.

### Dépréciations

Les 5 tools suivants sont **dépréciés** (`removal_version=0.3.0`) et
transformés en wrappers sécurisés (`legacy_execute=False` par défaut →
prépare un plan, aucune écriture BIMData) :

| Tool déprécié | Remplaçant actif |
|---|---|
| `suggest_classifications` | `list_classification_suggestions` |
| `create_bcf_topics` | `prepare_bcf_topics` + `apply_bcf_topics` |
| `create_smart_views` | `prepare_smart_views_plan` + `apply_smart_views_plan` |
| `apply_suggested_classifications` | `list_classification_suggestions` → `update_suggestion_status` → `prepare_classification_update_plan` → `apply_classification_update_plan` |
| `doe_enrich_model` | `match_doe_to_ifc` → `prepare_doe_enrichment_plan` → `apply_doe_enrichment_plan` |

Compatibilité préservée : aucun client MCP existant n'est cassé. Politique
de suppression progressive (N → N+1 → N+2) documentée dans
[docs/migration_prepare_apply.md](docs/migration_prepare_apply.md).

### Documentation

- [docs/mcp_tools.md](docs/mcp_tools.md) — référence des 46 tools (statut,
  R/W, confirm requis, remplaçant, risque métier).
- [docs/migration_prepare_apply.md](docs/migration_prepare_apply.md) —
  guide migration avec exemples avant/après pour les 5 tools dépréciés.
- [docs/workflow_amo_bim.md](docs/workflow_amo_bim.md) — workflow AMO BIM
  cible (12 étapes + sous-workflow DOE 4 étapes), diagramme Mermaid,
  politique de non-investissement sur `suggest_classifications`.

### Tests

- **+148 tests** (478 → 689) couvrant : domain filters, suggestion store,
  query filtering, MCP filter tools, plans (SHA-256 + sandbox), write
  journal, redaction secrets, 4 planners, classifier applier (linked/failed
  uuids), MCP prepare/apply tools, deprecation helpers, legacy wrappers,
  workflow E2E non destructif.
- `tests/integration/test_workflow_amo_bim_e2e.py` — **garde-fou
  architectural** : si une régression ré-introduit une écriture BIMData
  hors du pattern `prepare → apply(confirm=True)`, ce test échoue.

### PRs incluses

- #8 [feat: couche domain/query + pattern prepare/apply (2 tranches)](https://github.com/Slimouzi/audit-bim-i3f/pull/8)
- #9 [refactor(mcp): clean deprecated tools around prepare-apply workflow](https://github.com/Slimouzi/audit-bim-i3f/pull/9)
- #10 [feat(workflow): stabilisation AMO BIM — fix marker empty list + guide + test E2E](https://github.com/Slimouzi/audit-bim-i3f/pull/10)
- #11 [feat(doe): pattern prepare/apply pour l'enrichissement DOE → IFC](https://github.com/Slimouzi/audit-bim-i3f/pull/11)

## [0.1.0] — 2026-05-24

Première version publiable du MCP `audit-bim-i3f`.

### Ajouté

- **Architecture en 7 agents** orchestrés via FastMCP :
  - `requirements/` — parseurs des 3 documents MOA (CCH PDF + 2 annexes XLSX).
  - `extraction/` — client BIMData authentifié (OAuth2 / API Key / Bearer)
    avec dénormalisation `/element/raw`.
  - `audit/` — moteur de 6 règles : spatial, naming, classifications,
    properties (avec validateurs), uniqueness (identifiant équipement),
    lists. Hiérarchie IFC parent ↔ sous-classes (IfcWall ↔
    IfcWallStandardCase).
  - `classifier/` — suggester UniFormat II (heuristique multi-signaux),
    applier (création + liaison via API BIMData), reader XLSX modifié par
    l'auditeur. 4 référentiels (UF II / Omniclass / CCS / Table 3F).
  - `reporting/` — Word (python-docx + matplotlib) + XLSX (xlsxwriter)
    avec colonnes Suggestion + Confiance.
  - `bcf/` — BCF Topics 2.1 (workflow d'issues, panneau BCF Issues).
  - `smartview/` — Smart Views natives BIMData (panneau Smart Views) avec
    payload minimal aligné UI viewer.
  - `doe/` — agent DOE → IFC : extracteur Excel, matcher 4 stratégies
    (GUID/Tag/Nom fuzzy/localisation), enricher Psets.
- **19 tools MCP** : context_questions, set_owner_documents,
  parse_owner_requirements, get_catalog_properties,
  list_classification_systems, set_active_model, extract_model_snapshot,
  run_audit_tool, query_findings, generate_xlsx_annex,
  generate_word_report, suggest_classifications,
  apply_suggested_classifications, apply_classifications_from_xlsx,
  doe_match_only, doe_enrich_model, create_bcf_topics,
  create_smart_views, full_audit.
- **4 transports MCP** : stdio (défaut), http, sse, streamable-http
  (via flag `--transport`).
- **Persona AMO BIM** France (loi MOP, ISO 19650, NF EN 17412-1, CCH I3F)
  exposée comme prompt MCP `amo_bim_i3f`.
- **6 exemples d'intégration** : Claude Desktop, OpenAI Agents SDK,
  LangChain, CrewAI, Node.js (stdio + HTTP), Python direct.
- **167 tests pytest** sur les modules purs (validators, ifc_hierarchy,
  catalog, systems, suggester, doe/*, audit/engine, reporting/theming,
  extraction/normalizer).
- **Palette couleur sévérité** feux tricolores standard (CRITICAL rouge
  foncé / HIGH rouge / MEDIUM orange / LOW vert / INFO bleu).

### Découvertes API documentées (mémoire projet)

- Base URL BIMData : `https://api.bimdata.io` (pas `/v1`).
- OpenAPI spec : `https://api.bimdata.io/doc/schema` (auth requise).
- Smart View = BCF FullTopic avec `format: "bimdata-smartview"` dans le
  body (et non en query param).
- API Key BIMData scopée à un cloud unique.
