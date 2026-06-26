# Changelog

Toutes les évolutions notables de ce projet sont consignées dans ce fichier.

Format basé sur [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/), versioning
[SemVer](https://semver.org/lang/fr/).

## [Unreleased]

### Security

#### Montée des dépendances vulnérables (pip-audit)

- Résolution de 12 CVE remontées par le job CI `security-audit`
  (publiées après le dernier run de `master`, versions de deps
  inchangées depuis) :
  - `cryptography` 48.0.0 → 49.0.0 (GHSA-537c-gmf6-5ccf) ;
  - `pydantic-settings` 2.14.1 → 2.14.2 (GHSA-4xgf-cpjx-pc3j) ;
  - `pypdf` 6.12.1 → 6.14.2 (CVE-2026-49460/49461/54530/54531,
    GHSA-jm82-fx9c-mx94) ;
  - `python-multipart` 0.0.29 → 0.0.32 (CVE-2026-53538/53539/53540) ;
  - `starlette` 1.1.0 → 1.3.1 (CVE-2026-54282/54283).
- `uv.lock` régénéré (`uv lock --upgrade-package …`). `pip-audit` repasse
  au vert sur `requirements-from-lock.txt` et l'extra `[ocr]`.

## [0.4.1] — 2026-05-26

Patch de sécurité opérationnelle : ``full_audit`` ne corrompt plus la
cible active ni la phase de l'audit quand il est invoqué sans IDs ou
sans phase.

### Fixed

#### `full_audit` préserve la cible active (PR #22)

- **Bug** : ``full_audit(model_id=None)`` appelait inconditionnellement
  ``set_active_model(model_id=None)`` qui retombait sur
  ``config.MODEL_ID`` (lu depuis ``.env``). Conséquence concrète :
  après ``set_active_model(model_id="1673781")`` +
  ``verify_active_model(...)`` OK, un ``full_audit()`` écrasait
  silencieusement la cible avec le ``BIMDATA_MODEL_ID`` d'environnement
  → rapport généré sur la mauvaise maquette **malgré la vérification
  d'identité**.
- **Politique de préservation appliquée** :
  - IDs explicites (au moins un de ``cloud_id/project_id/model_id``)
    → ``set_active_model`` appelé (re-targeting volontaire).
  - Aucun ID + ``_State.client`` présent → cible préservée, pas de
    ``set_active_model``.
  - Aucun ID + pas de client → fallback ``.env`` (comportement
    historique des sessions fraîches).

#### `full_audit` propage la phase active (PR #22, follow-up CTO)

- **Bug** : la phase locale (argument ``phase: str = "PRO"`` de
  signature) était propagée à ``_validate_audit_context``,
  ``run_audit`` et ``merge_user_context``, même quand
  ``_State.phase`` avait été posée précédemment par
  ``set_active_model(phase="DOE")``. Le rapport Word affichait alors
  "PRO" alors que l'audit avait tourné en DOE.
- **Fix** : calcul d'une ``effective_phase`` au début de
  ``full_audit`` :
  - argument ``phase`` explicite non-"PRO" → gagne ;
  - sinon ``_State.phase`` si posée → on l'utilise ;
  - sinon fallback "PRO".
- ``effective_phase`` est propagée à la validation de contexte, à
  ``set_active_model`` (lors du re-targeting), et à
  ``merge_user_context`` (contexte Word).
- Quand la cible est préservée, ``_State.phase`` est désormais
  **alignée** sur ``effective_phase`` (au lieu de n'être mise à jour
  que si ``None``) — élimine la divergence audit/rapport quand un
  ``full_audit(phase="DCE")`` est appelé après
  ``set_active_model(phase="AVP")``.

#### `audit_bim.__version__` lu depuis les métadonnées du package

- **Bug historique** : ``audit_bim/__init__.py`` exposait
  ``__version__ = "0.1.0"`` codé en dur depuis l'origine du projet,
  jamais resynchronisé avec ``pyproject.toml`` (qui a déjà été bumpé
  à 0.2.x / 0.3.0 / 0.4.0 sans toucher ``__init__.py``).
- **Fix** : lecture dynamique via
  ``importlib.metadata.version("audit-bim-i3f")``. Source unique de
  vérité = ``pyproject.toml``. Les futures bumps n'ont plus à
  toucher deux fichiers. Fallback explicite
  ``"0.0.0+unknown"`` en cas de lecture du source sans
  ``pip install`` (CI exotique).

### Tests

- **+4 tests unitaires** (``tests/unit/test_mcp_full_audit_target.py``) :
  - préservation cible quand aucun ID fourni (scénario CTO complet,
    vérifie que ``set_active_model`` n'est pas appelé et que les IDs
    de session restent intacts face à un ``.env`` piège) ;
  - re-targeting explicite via IDs fournis ;
  - fallback ``.env`` quand session vierge ;
  - cohérence triple ``run_audit`` / ``merge_user_context`` /
    ``_State.phase`` quand ``phase`` est explicite et différente de
    ``_State.phase``.
- Suite unit : 835 → **839 passed**.

## [0.4.0] — 2026-05-26

Release de durcissement du pipeline d'audit (verrou d'identité du
modèle avant toute génération de livrable) et de refonte graphique
des rapports Word + Excel à la **charte Korhus.ai 2025 v1.0**.

### Added

#### Garde-fou d'identité du modèle BIMData (PR #20)

- **Nouveau module `audit_bim/mcp/model_identity.py`** — helpers purs
  `normalize_model_name(value)` et `model_matches_expected(model_name,
  expected)`. Comparaison insensible à la casse, aux accents et aux
  espaces multiples (ex: `"LIFFRE"` matche `"Maquette BIM - LIFFRÉ -
  DOE.ifc"`). Un pattern attendu vide désactive la vérification
  (rétro-compat).
- **Nouveau tool MCP `verify_active_model(expected_model_name,
  refresh_snapshot=True, use_cache=False)`** — confirme que la
  maquette BIMData active est bien celle attendue. Rafraîchit le
  snapshot **sans cache** par défaut, puis compare `model.name` au
  fragment attendu. Renvoie `{ok, project_name, model_name, model_id,
  modified_date, from_cache, message}`. Ne modifie jamais
  `_State.result` — utilisable comme contrôle préalable sans effet
  de bord sur un audit en cours. Outils MCP : 49 → **50**.
- **`full_audit` étendu** — nouvelles options `expected_model_name`
  (str | None, défaut `None`) et `force_refresh_snapshot` (bool,
  défaut `True`). Sur mismatch, l'orchestrateur lève `ValueError`
  **avant** toute génération de livrable. Comportement legacy
  préservé quand `expected_model_name=None`.
- **Pourquoi** : `set_active_model` invalide bien `_State.snapshot`
  et le cache disque est keyé par `model_id`, donc il n'y a pas de
  risque de contamination entre maquettes côté infrastructure. Le
  risque résiduel est **humain** — un mauvais `model_id`
  copié-collé produit un rapport cohérent sur la mauvaise maquette,
  silencieux et coûteux à découvrir. `verify_active_model` ferme
  cette fenêtre.

#### Charte graphique Korhus.ai pour les livrables (PR #19)

- **Refonte complète des rapports Word + Excel** à la *Brand
  Guidelines 2025 v1.0* Korhus.ai :
  - couverture sombre Korhus Primary `#0C101B` avec logo Korhus
    (variante claire/inversée),
  - supertitle + filet d'accent cyan `#59F4FF` sur les en-têtes,
  - police **Roboto** (fallback Arial),
  - tableaux KPI / référentiel sur fond Blue Neutral Light
    `#F0F5FF`, en-têtes sombres, lignes zébrées,
  - bandeau brandé « KORHUS.AI — AUDIT BIM » + filet cyan sur les
    onglets *Synthèse* et *Référentiel I3F* du XLSX.
- **Nouveau module `audit_bim/reporting/korhus_brand.py`** —
  résolution du brand kit via deux sources : variable d'env
  `KORHUS_BRAND_KIT_DIR` (recommandée) → scan sibling
  `korhus_brand_kit/` voisin du repo (confort local) → `None`. Pas
  de chemin hardcodé dans le code. Helper `find_logo(variant)` avec
  variantes `primary | dark | light | mark_primary | mark_dark |
  mark_light`.
- **Tokens brand-neutres dans `theming.py`** : `KORHUS_PRIMARY`,
  `KORHUS_SECONDARY`, `KORHUS_TERTIARY`, `KORHUS_GRANITE`,
  `KORHUS_BLUE_NEUTRAL_LIGHT`, `KORHUS_FONT_PRIMARY` (Roboto),
  `KORHUS_FONT_FALLBACK` (Arial). Les alias historiques `I3F_BLUE`,
  `I3F_BLUE_LIGHT`, `I3F_GREY` pointent désormais sur les
  équivalents Korhus (compatibilité ascendante des imports
  externes).
- **Dégradation gracieuse** : si le brand kit est absent (CI sans
  assets, autre poste), la couverture rend un wordmark texte
  « KORHUS.AI » à la place du logo. Le rapport reste générable —
  couvert par un test dédié.
- **Couleurs de sévérité inchangées** : la convention métier feux
  tricolores (rouge/orange/vert) reste indépendante de la charte de
  marque ; un finding CRITICAL reste visuellement critique même
  dans le rendu Korhus.

### Documentation

- **README.md — section « Vérifier la bonne maquette avant audit »**
  (PR #20) : workflow recommandé `set_active_model →
  verify_active_model → parse_owner_requirements → run_audit_tool →
  generate_xlsx_annex → generate_word_report(...)`, avec rappel
  explicite des 3 champs contexte obligatoires depuis v0.3.0
  (`project_address`, `project_phase`, `auditor_name`) ou
  `confirm_context=True`. Documentation de la réponse `needs_context`
  pour éviter aux utilisateurs (et à Claude Desktop) de tomber sur
  l'erreur silencieuse en bout de chaîne.
- **README.md — section « Charte graphique Korhus.ai »** (PR #19) :
  configuration du brand kit via `KORHUS_BRAND_KIT_DIR` (recommandée)
  ou voisinage local, rappel de la dégradation gracieuse, mention
  de la palette + typo.

### Tests

- **+39 tests unitaires** :
  - 21 pour le garde-fou identité (helpers normalisation/matching,
    `verify_active_model` ok/ko/no-client/no-snapshot/cache,
    `full_audit` mismatch interrompt avant les livrables, comportement
    legacy sans `expected_model_name` préservé).
  - 18 pour la charte Korhus (palette + alias I3F→Korhus,
    résolution du brand kit avec env override / fallback / absence,
    smoke render Word + Excel avec et sans logo).
- Suite unit : 774 → **835 passed**.

## [0.3.0] — 2026-05-26

Release de capacités métier visibles : requêtage tabulaire sémantique
des données BIM, rapport Word d'audit enrichi multi-sections, et garde
de gouvernance AMO BIM (3 champs de contexte obligatoires avant audit).

### Added

#### Requête tabulaire sémantique de la maquette (PR #15)

- **Nouveau module `audit_bim/query/property_aliases.py`** —
  résolveur sémantique FR/EN pour propriétés IFC/Pset avec matching
  exact → suffixe → fallback dynamique sur n'importe quel `Pset.Prop` :
  acoustique (`Rw`, `AcousticRating`,
  `IndiceAffaiblissementAcoustique`…), feu (`FireRating`,
  `DegreCoupeFeu`, `ResistanceAuFeu`…), dimensions (`Height` /
  `Hauteur` / `OverallHeight` / `BaseQuantities.Height`), matériaux
  (`Material` / `Materiau`), fabricant (`Manufacturer` / `Fabricant`
  / `Marque`), maintenance (`MaintenanceID` / `AssetID` / `IdGmao`).
- **Nouveau module `audit_bim/query/table_query.py`** — `BimQuery`
  (filter + fields + include_empty + flatten_lists + pagination) +
  `BimQueryResult` (columns + rows source-tracées + warnings).
  Fonction `query_bim_table(snapshot, query)` pure, sans I/O ni API.
- **3 nouveaux tools MCP** : `query_bim_data` (requête générique avec
  pagination ≤ 500 + overflow disque > 256 KB via
  `maybe_dump_to_disk`), `query_bim_preset`, `list_query_presets`.
- **3 presets initiaux** : `doors_acoustic_dimensions`,
  `walls_fire_acoustic`, `equipment_maintenance`.
- **Extension `BimObject`** : `get_property(name_or_alias)`,
  `get_quantity(name_or_alias)`, `dimensions_summary()`,
  `materials_summary()`.
- Outils MCP : 46 → **49**.

#### Rapport Word d'audit enrichi (PR #16)

- **Structure du rapport** : 6 → **13 sections**. Nouvelles sections :
  *Contexte de la mission*, *Description du projet*, *Référentiels et
  documents analysés*, *Attendus du projet*, *Objectifs BIM*, *Liste
  des contrôles réalisés* (tableau 4 colonnes), *Informations non
  disponibles*. Paragraphes explicatifs sur les figures du résumé
  exécutif et de la synthèse par thème.
- **Nouveau module `audit_bim/reporting/context.py`** —
  `ControlDescription` (Pydantic frozen) et `ReportProjectContext`
  (23 champs) couvrant projet, modèle, MOA, site/bâtiment/adresse,
  référentiel, attendus, objectifs BIM, contrôles, hypothèses,
  `missing_information` + comptages.
- **`build_report_context(result)`** : extracteur pur multi-sources
  (`snapshot.project`, `snapshot.model`, `snapshot.sites`,
  `snapshot.buildings`, `catalog`, `phase`) sans I/O ni API.
- **Garantie anti-hallucination** : aucune donnée inventée.
  Recherche d'objectifs BIM stricte (pas de fuzzy) ; mention
  *« Information non disponible dans les documents fournis. »* +
  recensement dans la section dédiée pour toute donnée manquante.
- **Rétrocompatibilité** : `write_word_report` accepte un paramètre
  optionnel `context: ReportProjectContext | None = None`.

#### Validation du contexte avant audit (PR #17)

- **Gouvernance AMO BIM** : `full_audit` et `generate_word_report`
  exigent désormais 3 champs de contexte avant tout lancement :
  `project_address`, `project_phase`, `auditor_name`. Un 1er appel
  sans contexte retourne `{"status": "needs_context", "missing": […],
  "questions": […]}` sans rien exécuter ; le 2e appel avec les
  champs lance l'audit / le rapport. `confirm_context=True` autorise
  un bypass d'urgence (les champs manquants apparaissent comme
  *Information non disponible* dans le rapport).
- **Traçabilité des sources** : nouveau champ
  `field_sources: dict[str, str]` dans `ReportProjectContext` avec
  4 valeurs (`user` / `extracted` / `deduced` / `missing`) et
  helper `source_of(field)`. Les valeurs `extracted` et `deduced`
  sont marquées dans le rapport Word (`_render_with_source`,
  suffixes *« (déduit de la maquette — à confirmer) »* /
  *« (déduit par heuristique — à confirmer) »*).
- **Helper `merge_user_context(ctx, *, project_address=,
  project_phase=, auditor_name=, …)`** : écrase les champs fournis,
  les marque `source="user"`, nettoie les entrées correspondantes
  dans `missing_information`. Les chaînes vides ou blanches sont
  ignorées. `project_phase` validée contre `BIMPhase`.
- **Anti-hallucination renforcée** : `auditor_name` jamais déduit
  d'un autre champ ; adresse IfcSite extraite marquée `extracted`
  (à confirmer) ; `merge_user_context(ctx)` sans input renvoie
  l'instance inchangée.

### Tests

- **+132 tests** (754 → 886). Aucune régression.

### Documentation

- `docs/mcp_tools.md` — nouvelle section *« Requête tabulaire
  sémantique »*.
- `docs/workflow_amo_bim.md` — sections *« Interroger la maquette »*,
  *« Rapport Word — contexte projet enrichi »*, *« Validation du
  contexte avant audit »*.

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
