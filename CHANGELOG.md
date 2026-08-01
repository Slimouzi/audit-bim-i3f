# Changelog

Toutes les évolutions notables de ce projet sont consignées dans ce fichier.

Format basé sur [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/), versioning
[SemVer](https://semver.org/lang/fr/).

## [Unreleased]

### Fixed (pack AVP — quantités absentes : livrable faux au lieu d'un refus)

- **Un pack pouvait sortir avec des lignes et des colonnes de quantités vides**
  — SHAB, Zones/Espaces, Menuiseries et Plancher remplis de « Information non
  disponible ». Plus dangereux qu'un livrable vide : il paraît complet et se
  lit comme un résultat. La QA gate ne comptait que les **lignes**, jamais les
  **valeurs**.
- **Cause** : le snapshot BIMData ne porte pas de `BaseQuantities` et les
  quantités calculées n'avaient pas été fusionnées — `generate_avp_i3f_pack`
  dépendait d'un `extract_model_snapshot(compute_missing_quantities=True, …)`
  préalable, sans moyen de le demander lui-même ni de signaler son absence.
- **`computed_quantities_json` ajouté à `generate_avp_i3f_pack`** : validé via
  le contrat `computed_base_quantities/v1`, fusionné **gap-only** dans le
  snapshot avant génération (jamais d'écrasement d'une valeur native), avec la
  couverture stockée sur le snapshot et rendue dans la réponse.
- **Nouvelle QA gate « quantités critiques vides »** : espaces sans aucune
  surface, menuiseries sans aucune largeur/hauteur, dalles sans aucune aire →
  refus explicite `error="missing_quantities"` + `needs_computed_quantities_json`
  et la marche à suivre, au lieu de produire le pack.
- **`list_avp_i3f_xls_reports` signale le besoin en amont**
  (`needs_computed_quantities_json`, `reports_without_quantities`,
  `next_action`) — pour fournir le JSON avant de générer, pas pour découvrir le
  refus après.
- Tests : `test_avp_pack_computed_quantities.py` (12) — refus sans JSON,
  génération avec, et **valeurs numériques réellement présentes** dans les
  quatre annexes (SHAB, Zones/Espaces, Menuiseries, Plancher), traçabilité
  « Calculée (IfcOpenShell) », fusion gap-only préservant le natif, schéma
  inconnu refusé avant génération.

### Fixed (pack AVP — identité projet et auteur du contrôle)

- **Un pack pouvait être livré au nom d'un AUTRE chantier.** Le classeur de
  contrôle MOA est auto-découvert dans les documents maître d'ouvrage ; son
  entête « Projet » / « ESI » servait ensuite d'identité projet. Auditer Dieppe
  avec le classeur de référence Tarare produisait donc des fichiers
  « … Tarare 0546L AVP - … ». **Tarare 0546L est un exemple MOA**, jamais une
  valeur par défaut produit.
- **Ordre de résolution strict** : paramètre explicite → contexte du modèle
  actif → **on demande sans générer**. L'entête du classeur n'est plus
  autoritaire ; elle n'est proposée en `suggestion` que si l'appelant a désigné
  le classeur lui-même. Un classeur auto-découvert ne suggère rien.
- **`project_name` / `project_code` ne sont plus contournables** par
  `confirm_context` : ils nomment des fichiers remis au client.
  `confirm_context` ne couvre plus que le contexte documentaire (phase, auteur).
- **Plus aucun nom générique** : le repli `project_name="Projet"` est supprimé,
  et `generate_word_report` n'a plus de défaut `auditor="AMO BIM (audit
  automatisé)"` — sans nom fourni, l'auteur reste non renseigné plutôt
  qu'inventé.
- **`auditor_name` exposé par `generate_avp_i3f_pack`** — le prompt guidait
  vers un paramètre que le tool n'avait pas (`TypeError` à l'appel). Ordre de
  résolution : `auditor_name` (à employer) → `auteur_controle` (vocabulaire
  I3F) → `auditor` (historique). La question `needs_context` porte désormais la
  clé `auditor_name`, avec `accepted_aliases` — une clé de question doit
  correspondre à un paramètre réel.
- **`generate_word_report` valide `auditor_name or auditor`** : un appel
  historique `auditor="Stan"` repartait en `needs_context` avant d'atteindre le
  repli prévu.
- **Prompt AMO** : demander l'identité projet et `auditor_name` **avant** la
  première génération (proposition d'utiliser le nom de session, sinon
  demande explicite) — ne plus générer puis proposer de régénérer.
- Tests : `test_avp_pack_no_example_identity.py` (8) — sans identité on demande
  et **rien n'est écrit** ; `confirm_context` ne débloque pas ; l'identité du
  template MOA n'atteint ni les noms ni le contenu des livrables ; avec
  `project_name="Dieppe"` / `project_code="7427L"` tous les fichiers commencent
  par `260801 Dieppe 7427L AVP - `. Les tests qui encodaient l'ancien
  comportement (« l'entête Tarare gagne ») sont recalés sur la règle inverse.

### Changed (contrats JSON — validation centralisée dans bim-core)

- **Les JSON échangés avec le MCP géométrique sont désormais des contrats
  versionnés** (`bim-core>=0.2.0`, sous-package `bim_core.contracts`) :
  `envelope_quantities/v1` et `computed_base_quantities/v1`. Audit-bim ne
  réimplémente plus ni la validation ni la normalisation.
- **Politique de schéma appliquée AVANT toute fusion / génération** :
  document V1 accepté ; `schema` présent mais inconnu ou invalide (`null`,
  `""`, `0`, `False`, autre famille de contrat) **refusé** ; fichier
  historique **sans** `schema` accepté uniquement s'il correspond à une forme
  legacy connue, migré explicitement vers V1 avec l'avertissement
  `legacy_schema_missing`.
- **`BIM_CORE_JSON_STRICT_SCHEMA=true`** supprime la tolérance legacy — de quoi
  vérifier qu'un parc de fichiers est entièrement migré. Ce mode deviendra le
  défaut ; la compat sans `schema` est temporaire.
- **`read_envelope_json`** (annexe « Extraction surface enveloppe ») et
  **`load_computed_quantities`** (fusion gap-only) délèguent à
  `load_envelope_quantities` / `load_computed_base_quantities`. La
  normalisation des alias de clés (`netsidearea_m2`, `nombre`, `etages` en
  chaîne, `seuil_3f`) **disparaît d'audit-bim** : elle vit dans le contrat.
- **Compatibilité préservée** : toutes les erreurs de contrat héritent de
  `ContractError`, elle-même une `ValueError` — les appelants qui attrapaient
  `ValueError` fonctionnent sans changement. Seul le libellé change
  (« Schéma non reconnu »).
- Bump des pins first-party : bim-core v0.2.0, bimdata-read v0.1.6,
  bimdata-write v0.1.4, bim-query v0.1.3, bim-publication v0.1.3,
  bim-audit-engine v0.1.4. Ces briques n'ont pas besoin des contrats, mais uv
  refuse deux URLs Git différentes pour un même paquet : toutes doivent pointer
  le même tag bim-core.
- Tests : `test_json_contract_consumption.py` (22) — fichier **réel**
  `250613_MN_BAT_envelope.json` (sans `schema`) accepté via migration, document
  V1 producteur accepté sans avertissement, schémas invalides refusés avant
  fusion, mode strict refusant le legacy, et livrable enveloppe non vide dans
  les deux cas.

### Changed (reporting AVP — découpage interne, façade conservée)

- **`audit_bim/reporting/avp_i3f.py` (2 527 lignes) découpé** en package interne
  `audit_bim/reporting/avp/` : `models.py` (métadonnées, `AvpReportPack`, convention de
  nommage des livrables), `pack.py` (orchestrateur + QA gate), `xlsx_common.py` (helpers
  d'écriture partagés), `xlsx_controle.py`, `xlsx_enveloppe.py`, `xlsx_shab.py`,
  `xlsx_zones.py`, `xlsx_menuiseries.py`, `xlsx_plancher.py`, `docx_analyse.py`.
  Dépendances **descendantes uniquement** : `pack` connaît les builders, jamais l'inverse.
- **`avp_i3f.py` devient une façade** (~60 lignes) : ré-exporte `write_avp_i3f_report_pack`,
  `AvpMeta`, `AvpReportPack`, `AvpQaError`, `build_sources_from_snapshot` et les points de
  patch privés historiques. **Tous les imports existants restent valides**, sur *les mêmes
  objets* (aucune logique dupliquée).
- **Refactor pur** : aucune logique métier modifiée, aucun nom de fichier livrable changé,
  aucune sortie modifiée (comparaison AST des définitions avant/après : seul l'orchestrateur
  change, pour appeler les builders nommés `build_shab_xlsx` / `build_zones_xlsx`).
- Tests : `test_avp_facade_identity.py` — anciens imports valides, identité des ré-exports,
  façade sans implémentation résiduelle (garde-fou anti-regrowth), 7 noms de livrables figés.
  Tests existants **inchangés**.

### Changed (surface MCP — aliases métier en compat LEGACY opt-in)

- **Réduction de la surface exposée par défaut** : les **8 aliases métier**
  (`prepare_bcf_from_findings`, `apply_bcf_plan`, `prepare_smartviews_from_findings`,
  `apply_smartviews_plan`, `prepare_classification_corrections`,
  `apply_classification_corrections`, `prepare_doe_enrichment_from_file`,
  `apply_doe_enrichment`) ne sont **plus enregistrés par défaut** → 53 → **45 tools**
  canoniques (moins de bruit côté Claude/harness).
- **Opt-in de compat** via **`AUDIT_BIM_ENABLE_LEGACY_ALIASES=true`** (`1`/`true`/`yes`/`on`).
  Absent ou faux ⇒ `audit_bim/mcp/aliases.py` **n'est pas importé**. `server.py` ne tire
  plus `aliases` au niveau module : les ré-exports de compat `server.<alias>` sont
  **lazy** (PEP 562). **Aucun changement** des tools canoniques ni de leur payload.
- **Prompt AMO recalé sur les tools canoniques** : le workflow DOE du prompt
  recommandait `prepare_doe_enrichment_from_file` / `apply_doe_enrichment` (aliases
  désactivés par défaut) → remplacés par `prepare_doe_enrichment_plan` /
  `apply_doe_enrichment_plan`. Un test interdit tout alias LEGACY dans
  `AMO_BIM_I3F_PROMPT` en mode par défaut (sinon Claude appellerait un tool absent).
- **Docs recalées** : `docs/mcp_tools.md` et `docs/workflow_amo_bim.md` — le workflow
  recommandé n'emploie que des noms **canoniques** ; les aliases sont regroupés dans une
  section « Aliases LEGACY (opt-in) » dédiée.
- **Compat lazy complète** : `apply_doe_enrichment` ajouté à `_LEGACY_ALIAS_REEXPORTS`
  (les 8 aliases accessibles via `server.<alias>`).
- Tests : inventaire en sous-processus (`test_mcp_aliases_optin.py`) — aliases absents par
  défaut / présents sous le flag / canoniques inchangés dans les deux modes ; + garde prompt.

### Added (MOA — rapport « Contrôle maquettes » + rapport d'analyse consolidé)

- **Rapport « Contrôle maquettes »** au format MOA (grille de contrôle + onglets
  statistiques) : grille remplie depuis l'audit BIM (`POINTS DE CONTROLE`) et, si un
  classeur source `… controle maquettes.xlsx` est disponible, **mode template** qui
  reconstruit les feuilles MOA attendues (`Grille de contrôle` + feuilles stats) et
  rafraîchit les métadonnées (projet, date d'analyse).
- **`… Rapport analyse BIM.docx`** (+ `.pdf` best-effort) — rapport consolidé : pages
  grille de contrôle MOA et annexes alimentées depuis le `controle_xlsx` quand il est
  fourni. 7ᵉ livrable du pack AVP.
- **Auto-découverte des sources** dans les racines d'entrée : `generate_avp_i3f_pack`
  résout automatiquement un `envelope.json` unique et un `… controle maquettes.xlsx`
  unique (retourne `controle_xlsx_used` / `envelope_json` effectivement utilisés) ;
  un argument explicite reste prioritaire.
- **Reformulation honnête** : la génération courante **reconstruit** les onglets /
  colonnes / formules principales au format MOA (sans bandeau BIMData) mais ne préserve
  pas pivots et styles natifs. Le verrou `_MOA_TEMPLATE_MODE_AVAILABLE` reste **False**
  → `can_generate_identical` **toujours False** (repro stricte = futur mode `moa_template`).

### Fixed (Extraction surface enveloppe — envelope.json prime sur le snapshot)

- **Correctif : le pack AVP retombait sur le repli « 484 murs » du snapshot** malgré un
  `envelope_json` fourni. `_ifc_first_sources` fait désormais **primer** la source
  `envelope.json` (détectée via `_is_envelope_json_source`) sur `build_sources_from_snapshot`,
  au lieu de l'écraser.
- **`read_envelope_json` tolère les variantes de noms de champs** du contrat réel :
  `net_side_area_m2` / `netsidearea_m2`, `n` / `nombre`, et `etages` en **liste** (jointe
  « R+1, R+2 ») ou en chaîne. `hors_filtre_type` accepte de même `net_side_area_m2`.
- Test de non-régression : snapshot présent **et** `envelope_json` présent ⇒ onglet MOA à
  **8 lignes métier** (pas 484), via le chemin complet `write_avp_i3f_report_pack`.

### Changed (Extraction surface enveloppe — logique MOA IfcOpenShell)

- **L'annexe « Extraction surface enveloppe » ne somme plus les murs élémentaires du
  snapshot.** Nouveau `read_envelope_json` (source structurée `envelope.json` du MCP
  ifc-geometry) : **une ligne métier par type** (`par_type`) et non par mur → onglet
  « TDB 2022 04.2 - Extraction s... », colonnes A-J au format MOA. Les colonnes **Solibri
  deviennent IFC OpenShell** (« Surface IFC OpenShell », « IFC OpenShell Surface des
  Fenêtres / des Portes »). `hors_filtre_type` reste **hors du total métier** (diagnostic).
  Synthèse type Tarare (Superficie des façades, écart IFC OpenShell vs Archicad BQ,
  menuiseries, SHAB, ratio FAC/SHAB, Seuil 3F). `generate_avp_i3f_pack` gagne
  `envelope_json` (prioritaire sur le repli snapshot et le `.xlsx`).

### Added (quantités calculées — Lot 4 : restitution & traçabilité)

- **Colonne « Source quantité »** dans les 4 exports snapshot du scope DIEPPE (SHAB,
  Zones/Espaces, Menuiseries, Plancher) : `Maquette` (BaseQuantity native BIMData) vs
  `Calculée (IfcOpenShell)` (valeur fusionnée au Lot 3) — un **gap** reste `NOT_AVAILABLE`
  (jamais masqué). Enveloppe **non** couverte (phase 2).
- **Note méthodo** apposée sous les tables contenant des valeurs calculées : « Quantités
  partiellement calculées par analyse géométrique IfcOpenShell — valeurs NON contractuelles,
  en attente d'un ré-export maquette avec BaseQuantities natives. »
- **`list_avp_i3f_xls_reports` : statut `partial_computed`** (+ champ `computed_assisted`)
  quand un rapport n'est générable que grâce aux BaseQuantities calculées ; `next_action`
  l'explicite. Les **gaps restants ne sont pas masqués** (`missing_data`).
- **Rapport consolidé `.docx`** : bloc « Quantités calculées (IfcOpenShell) — couverture »
  (`n_merged`, `n_gap_kept`, `n_skipped_status`, `n_unknown_uuid`, depuis
  `snapshot.computed_coverage`).

### Added (quantités calculées — Lot 3 : fusion dans le snapshot)

- **`extract_model_snapshot(compute_missing_quantities=True, computed_quantities_json=…)`**
  — fusionne les BaseQuantities calculées (JSON `computed_base_quantities/v1` du MCP
  `ifc-geometry`) dans le snapshot BIMData, en **gap-only** :
  - jointure par `BimObject.uuid == global_id` ; schéma validé (sinon erreur claire) ;
  - **jamais d'écrasement** d'une valeur BIMData native ; entrées `status != "computed"`
    ignorées ; `global_id` inconnu ignoré avec warning ;
  - **provenance par valeur** conservée (`computed_base_quantities` sur l'élément :
    `source="computed_ifcopenshell"`, `method`, `unit`, `status`), exposée par
    `get_object_detail` (`object.computed_base_quantities`) ;
  - la valeur est injectée dans les `property_sets` → lue à l'identique par les builders
    AVP et `bim_object_from_element` (déblocage automatique des rapports) ;
  - **clé de cache dédiée** (`cloud:project:model:modified:json_sha:compute`) dans le
    résumé ; fusion ré-appliquée sur un snapshot brut frais à chaque appel (le cache
    snapshot ne stocke que le brut → un appel standard ne voit jamais l'enrichi, et
    inversement ; invalidation naturelle quand le JSON change) ;
  - `compute_missing_quantities=False` (défaut) → comportement **historique inchangé**.

### Added (quantités calculées — Lot 1 : téléchargement du .ifc source)

- **`download_model_ifc(cache_dir=".audit_cache", overwrite=False)`** — tool MCP
  (lecture seule) : télécharge le **fichier .ifc** du modèle actif (URL signée
  `document.file` de `get_model`) en **streaming disque** (jamais chargé en RAM),
  sous plafond `AUDIT_MAX_IFC_MB` (défaut 500). Cache local `<cache_dir>/ifc/`
  keyé `model_id` + `modified_date` (même invalidation que le cache snapshot).
  Fondation du flux « quantités calculées » : fournit le .ifc au MCP
  `ifc-geometry` (`complete_ifc_base_quantities`) pour combler les BaseQuantities
  absentes. Nouveau `config.AUDIT_MAX_IFC_MB`.

### Changed (MCP I3F — full audit par défaut)

- **`full_audit` ne demande plus le choix de publication par défaut côté MCP.**
  `push_mode` vaut désormais `"none"` : l'appel nominal lance l'audit complet,
  génère les livrables Word/XLSX/JSON, et ne prépare aucune publication BIMData.
  Le mode `"ask"` reste disponible uniquement si l'agent ou l'utilisateur le
  demande explicitement.
- **Prompt AMO I3F recentré sur le chemin nominal.** Après ciblage maquette +
  preuve d'accès, l'agent doit proposer `full_audit(push_mode="none")`. Les
  propositions de correctifs de classification passent dans un deuxième temps,
  sur demande, via le workflow `list → accept/reject → prepare → apply`.

### Added (catalogue des rapports XLS MOA + rapport plancher)

- **`list_avp_i3f_xls_reports(include_templates=True, require_identical=False)`** — tool
  MCP **sans effet de bord** : sonde le snapshot courant (entités IFC, BaseQuantities,
  relations zone/espace, calque d'enveloppe) et rend, pour les 6 rapports MOA AVP, un
  verdict `{can_generate, can_generate_identical, status, available_data, missing_data,
  next_action}`. Étape à appeler **avant** `generate_avp_i3f_pack`. **Ne promet pas « à
  l'identique »** sur le seul snapshot : toute colonne Solibri/source externe absente →
  `can_generate_identical=False` (statut `partial`).
- **Catalogue déclaratif** `reporting/avp_report_catalog.py` (`ReportSpec` /
  `DataRequirement` / `ReportAvailability`) + vérif `reporting/avp_availability.py`
  (`inspect_avp_report_availability`).
- **Rapport `plancher`** (dalles `IfcSlab`, repli `IfcCovering`) ajouté au catalogue **et
  au pack** : `AvpSources.plancher` / `AvpSourcePaths.plancher` / `read_plancher` /
  `build_plancher_from_snapshot` / `_DELIVERABLE_LABELS["plancher"]` /
  `AvpReportPack.plancher_xlsx` / QA gate dédiée. `generate_avp_i3f_pack` gagne le
  paramètre `plancher_xlsx` et produit désormais **6 Excel** (comportement des 5 autres
  livrables **inchangé**). Le classeur plancher étant **à deux onglets** (« … Dalles Ok »,
  « Planchers »), il est modélisé en `MultiSheetSource` (tous les onglets source préservés,
  comme SHAB/Zones).

  Justesse du verdict de disponibilité (revue CTO) :
  - une **source XLS** chargée pour un rapport **satisfait toutes ses colonnes** (métier ET
    Solibri) → plus de faux `blocked` en source-only ;
  - `controle_maquettes` requiert un **AuditResult** (audit lancé) **ou** une source
    Contrôle I3F pour remplir la grille — le seul snapshot ne suffit pas (nouveau
    paramètre `has_audit_result`, câblé sur `_State.result`) ;
  - **`can_generate_identical` n'est jamais `True`** tant que le mode `moa_template`
    (copie du workbook, préservation formules/pivots/styles) n'est pas livré : la
    génération courante lit en `data_only` et réécrit des tables brandées → on ne
    promet **pas** « à l'identique », même sources Solibri fournies (garde
    `_MOA_TEMPLATE_MODE_AVAILABLE = False`). Rapport générable ⇒ statut `partial`.

### Fixed (diagnostic auth honnête)

- **`check_bimdata_access` renvoyait un dict sur 404 mais **remontait une exception
  brute** sur 401/403.** `bimdata_read._get` lève `BIMDataAuthError` (une
  `PermissionError`) pour 401/403 *avant* `raise_for_status`, alors que le tool
  n'attrapait que `requests.HTTPError` → un 401 remontait « BIMData 401 on … » sans
  `auth_source`/`auth_scheme`, masquant la vraie cause (clé API périmée). Ajout d'une
  branche `except BIMDataAuthError` qui renvoie `{ok: False, auth_source, auth_scheme,
  error}` ; le message 401 nomme le schéma rejeté et pointe les causes typiques (clé
  révoquée, `${BIMDATA_API_KEY}` non substitué). Le mapping 401 de la branche
  `requests.HTTPError` (code mort) est retiré.

### Added (avertissement d'auth au démarrage)

- **`warn_bimdata_auth_mode()`** (appelé par `assert_startup_config`, **tous
  transports**) : logge le mode d'auth BIMData **effectif** (précédence
  `access_token → api_key → OAuth2`, sans journaliser de valeur de credential), et **avertit** quand
  plusieurs modes sont configurés simultanément — un credential de rang supérieur périmé
  masque silencieusement un mode inférieur valide (cause racine d'un 401 « inexplicable »).
  Transforme une panne d'exécution opaque en signal de configuration au boot.

### Changed (ciblage explicite + auth non ambiguë)

- **Le runtime cible BIMData par IDs explicites uniquement.** `set_active_model` et
  `full_audit` **n'acceptent plus `bimdata_url`** (ni une URL collée dans `model_id`,
  désormais refusée avec un renvoi vers `parse_bimdata_target`). Une URL viewer est un
  **format d'entrée** : la convertir en IDs *avant* l'appel MCP. `resolve_bimdata_target`
  ne contient plus de résolveur d'URL caché.
- **`set_active_model` ne prétend plus prouver l'accès.** Sa réponse renvoie
  `auth: "configured"` (+ `auth_status: "configured"` + `note`) au lieu du trompeur
  `auth: "ok"` : configurer la cible/l'auth ne prouve pas l'autorisation BIMData.

### Added

- **`parse_bimdata_target(url)`** — tool : extrait `cloud_id`/`project_id`/`model_id`
  d'une URL viewer, à appeler avant `set_active_model` (aucun effet de bord).
- **`check_bimdata_access()`** — tool smoke cible/auth : lit `get_project` + `get_model`
  **sans cache** et prouve l'accès. `{ok, cloud_id, project_id, model_id, project_name,
  model_name, auth_source, auth_scheme}` ; sur `401` → « BIMData a rejeté la credential
  utilisée par le processus MCP pour cette cible » (formulation prudente : ni conclusion
  de droits ni preuve que la clé est invalide ailleurs ; 403 = sans droits, 404 = cible
  introuvable). Le couple `auth_source`/`auth_scheme` **rapporte le mode d'auth du
  processus** (déploiement clé serveur attendu : `auth_source: BIMDATA_API_KEY`,
  `auth_scheme: ApiKey`) sans jamais divulguer la valeur du secret. La provenance est lue
  depuis la **config serveur** (`config.*` immuable), *pas* depuis l'instance client : le
  flow OAuth2 écrit `client.access_token` **dès la construction**, l'attribut ne fait donc
  pas foi. Sert de sonde de vérification post-déploiement. Workflow recommandé
  (prompt/README/docs) : parse-URL → set (IDs) → **check_bimdata_access** →
  extract(use_cache=false) → continuer si `snapshot_health != "empty_model"` et
  `n_extraction_errors == 0` → audit.

### Removed

- **Garde `assert_snapshot_usable` retirée (décision produit).** Le contrôle
  consommateur de C2 (refus d'un snapshot vide / partiel / `status ≠ C`) et le message
  de statut associé sont supprimés à tous les points d'appel (`extract_model_snapshot`,
  `full_audit`, `verify_active_model`). L'extraction/l'audit renvoie désormais ce que
  BIMData fournit, y compris vide/partiel. Le champ `ModelSnapshot.extraction_errors`
  et le refus de cache partiel (côté `bimdata-read`) restent en place — ce ne sont pas
  des contrôles bloquants.

### Fixed (audit profond 2ᵉ passe — Lot 5, hygiène ops)

- **Extraction snapshot robuste à une racine d'export en lecture seule.**
  `extract_model_snapshot` appelait `safe_export_dir(cache_dir)` **inconditionnellement**
  (même `use_cache=False`) → `get_export_root()` faisait un `mkdir` sur
  `AUDIT_OUTPUT_DIR` (défaut `./out` → `/out` en conteneur, CWD=/), qui **plantait**
  (Errno 30) si le volume était monté read-only — l'extraction (une lecture) devenait
  impossible quels que soient `cache_dir`/`output_dir`. Désormais : la racine n'est
  touchée que si `use_cache=True`, et un échec d'accès (OSError) **dégrade en
  extraction sans cache** au lieu de planter (idem `verify_active_model`).
  `.env.example` documente que `AUDIT_OUTPUT_DIR` doit être inscriptible (piège
  `/out` read-only en conteneur).
- **`verify_active_model(use_cache=True)` — cache sandboxé.** Il écrivait
  `.audit_cache` sous le **CWD** (hors `AUDIT_OUTPUT_DIR`), contrairement à
  `extract_model_snapshot`. Le dossier passe désormais par `safe_export_dir`.
- **xlsx corrompu → erreur claire.** `read_classifications_from_xlsx` remontait un
  `BadZipFile` brut sur un fichier tronqué/non-zip ; converti en `ValueError` métier
  (« Fichier xlsx illisible ou corrompu »).
- **`set_owner_documents` invalide le catalogue.** Un changement de documents MOA
  laissait `_State.catalog` en place → un audit ultérieur tournait sur l'**ancien
  référentiel** (incohérent avec `full_audit` qui reconstruit). Le catalogue est
  désormais invalidé dès qu'un document change.
- **`.gitignore` — artefacts de couverture** (`.coverage`, `.coverage.*`,
  `coverage.xml`, `htmlcov/`) ne sont plus suivis par git.

### Tests (audit profond 2ᵉ passe — Lot 4, la suite verrouille)

- **E11 — invariants structurels des goldens (anti-tautologie).** Les goldens de
  parité publication sont régénérables depuis les mêmes builders (façades
  `bim-publication`) → régénérer compare le package à lui-même. Ajout d'**invariants
  de payload indépendants** (clés obligatoires BCF/Smart View, préfixe `I3F Audit — `,
  `format=bimdata-smartview`, `models` contient le model_id, `kind`/`target` des
  plans), vérifiés **à la fois** sur la sortie fraîche du builder **et** sur les
  fichiers golden — un golden régénéré depuis un builder cassé échoue désormais.
- **E2-bis — `field_path` : repli sur le libellé humain supprimé + verrou sur
  catalogue paramétré.** `_property_field_path` faisait un repli
  `pset_or_attribute or property_name` (libellé humain, espaces/accents), en
  contradiction avec sa propre docstring. Repli **supprimé** : le field_path se dérive
  du seul locateur technique (no-op pour les catalogues réels, toujours dotés d'un
  locateur ; un spec dégénéré produit désormais un chemin non grammatical **attrapé**
  par le verrou au lieu d'une chaîne « propre » masquant le défaut). Le verrou
  `field_path` tournait uniquement sur le fixture à 4 specs propres → les branches
  paramétrées par le catalogue lui échappaient : ajout d'un test qui exerce le verrou
  sur un catalogue à spec dégénérée + assertion « chaque règle émet ≥ 1 finding ».
- **E14 — job CI OCR dédié (tesseract).** Les tests OCR étaient **toujours skippés**
  en CI (binaire tesseract + extra `[ocr]` absents) alors qu'un job `pip-audit` OCR
  existait → fausse confiance. Nouveau job `ocr` : installe `tesseract-ocr` +
  `tesseract-ocr-fra` + `poppler-utils` et l'extra `[ocr]`, exécute
  `test_ocr_robustness` + `test_doe_ocr`, et **échoue si aucun test OCR n'a
  réellement passé** (garde anti-skip silencieux). Validé localement : 20 tests OCR
  passent.
- **Arch-lock — le verrou de couches attrape le contournement par re-export.**
  `from audit_bim import reporting` (import au niveau **package**) n'enregistrait que
  la cible `audit_bim` (couche `None`) → l'arête `audit_bim.reporting` était invisible
  et un module bas pouvait contourner la règle. `_imported_modules` résout désormais
  chaque **nom** importé comme sous-module potentiel (`base.name`) : on verrouille le
  **principe**, pas seulement 4 arêtes nommées. Méta-test ajouté + garde des 4 arêtes
  gelées. (Aucune violation réelle dans le code actuel.)
- **E12 — verrou du `conformity_rate`.** Trou de mutation : changer un poids
  (CRITICAL 5 / HIGH 3 / MEDIUM 1 / LOW 0.3 / INFO 0) ou le dénominateur
  (`n_éléments × 3`) ne cassait aucun test, alors que ce taux pilote la décision au
  **seuil 0.7** des livrables. Épinglé : valeur exacte (cas mixte), chaque poids
  isolé, mise à l'échelle du dénominateur, bornes [0,1], et comportement **au seuil**
  (0.70 pile n'est pas « < 0.7 »). Nouveau `tests/unit/test_conformity_rate_e12.py`.
- **E13 — couverture `on_get_prompt` / `on_read_resource`.** Ces handlers du
  `SessionBindingMiddleware` bindent `current_session` mais n'étaient testés par rien
  (une fuite d'état inter-sessions via prompts/resources serait passée). Bind + reset
  + isolation par clé + reset sur exception. Nouveau
  `tests/unit/test_middleware_prompt_resource_e13.py`.

- **C4 — le corps post-confirm des 3 `apply_*` (hors BCF) est enfin couvert.** Seul
  `apply_bcf_topics` avait le trio complet ; `apply_smart_views_plan`,
  `apply_classification_update_plan` et `apply_doe_enrichment_plan` n'exécutaient
  jamais leur corps post-`confirm` en test (une régression type `verify_checksum=False`
  y serait passée verte). Trio dupliqué sur les 3 (execute avec `confirm=True` +
  appel client vérifié ; rejet d'un plan **altéré** ; rejet d'un **mismatch de cible**)
  dans `tests/unit/test_mcp_prepare_apply_tools.py`.

### Fixed (audit profond 2ᵉ passe — Lot 3, écritures sûres)

- **E10 — redaction élargie + masquage d'erreurs en réseau.** (1) `redact_secrets`
  couvre désormais les **URLs signées** (`X-Amz-Signature`/`X-Amz-Credential`/
  `X-Amz-Security-Token`/`Signature`/`sig`/`token`) et les **chemins absolus serveur**
  (`/Users`, `/home`, `/tmp`, `/var`… → `<path>` ; les routes API `/cloud/…` sont
  préservées). Les retours `str(e)` de `classifier/applier` (×3) et de
  `apply_classifications_from_xlsx` (`reason`) sont scrubés. (2) Nouveau
  `ErrorMaskingMiddleware` : en transport **réseau**, une exception non gérée d'un tool
  est journalisée **redactée** côté serveur et remplacée par un message générique pour
  le client (les chemins/URLs signées ne fuient plus). En local (stdio/script), l'erreur
  brute est conservée. Choisi en middleware car `mask_error_details` ne peut pas être
  fixé à la construction de `mcp` (importé avant que le transport soit connu). Nouveaux
  `tests/unit/test_error_masking_e10.py` + cas dans `test_security_redaction.py`.
- **E9 — sérialisation intra-session des `tools/call`.** `_Session` était mutable sans
  verrou et les tools sync tournent en threadpool : deux appels concurrents d'un même
  client pouvaient s'entrelacer — un `set_active_model` (cible B) pendant un
  `full_audit` (findings A) → plan « findings A / cible B » scellé et applicable.
  `SessionBindingMiddleware.on_call_tool` prend désormais un verrou **par session**
  autour de l'exécution. Verrou **`asyncio.Lock`** (et non `threading.RLock` comme
  suggéré) : le middleware est asynchrone et tient le verrou à travers un `await` — un
  verrou bloquant figerait l'event-loop ; l'`asyncio.Lock` suspend la coroutine
  concurrente sans bloquer, et reste **par session** (la concurrence inter-clients est
  préservée). Nouveau `tests/unit/test_session_lock_e9.py`.
- **E8 — `set_active_model` invalide le store de suggestions.** Il remettait à zéro
  `snapshot` et `result` mais **pas** `suggestion_store` : construit sur les UUIDs du
  modèle précédent, il aurait produit un plan de classifications scellé sur la
  **nouvelle** cible mais portant les UUIDs de l'**ancien** modèle → écritures
  parasites (`validate_target` ne contrôle que la cible, pas la provenance). Le store
  est désormais invalidé avec les autres caches. Nouveau
  `tests/unit/test_session_invalidation_e8.py`.
- **C3 — un crash mid-apply ne duplique plus au re-run.** Les 4 planners
  journalisaient **après** la boucle d'items : un crash à l'item 3/5 laissait le
  journal vide (« rien ne s'est passé ») alors que 3 écritures étaient déjà faites
  chez le client ; le plan restant applicable, un re-run rejouait les 5 → doublons.
  `run_apply` (choke point des 4 planners) trace désormais l'**intent** (marqueur
  `<plan_id>.started` + entrée journal `status=started`) **avant** la boucle, un
  **completed** (marqueur `<plan_id>.applied.json` des items impactés + entrée
  journal, forme d'origine **inchangée**) **après**, et **refuse** un second apply
  du même `plan_id` — qu'il ait abouti ou été interrompu — sauf `force=True`.
  Nouveau `tests/unit/test_actions_planners.py::TestApplyIdempotencyC3`.

### Fixed (audit profond 2ᵉ passe — Lot 2, infra ≠ métier)

- **C2 — l'infrastructure ne se déguise plus en métier.** Une extraction BIMData
  échouée (token expiré, cible injoignable) produisait un snapshot vide ; l'audit
  déroulait dessus et livrait « pas d'IfcSite/IfcBuilding » (CRITICAL spatial) au
  lieu d'une erreur d'infra. Pire, un snapshot partiel mis en cache resservait son
  vide indéfiniment. Corrigé **cross-repo** (tags immuables) :
  `bim-core v0.1.2` ajoute `ModelSnapshot.extraction_errors` ; `bimdata-read v0.1.5`
  l'**attache** au snapshot et **ne met plus en cache un snapshot partiel** (schéma
  cache v2). *(Le garde consommateur `assert_snapshot_usable` initialement ajouté a
  été retiré par la suite — cf. section « Removed » — sur décision produit ; le champ
  `extraction_errors` et le refus de cache partiel restent.)* Cascade de pins
  (résolution uv unique, **aucun override**) : `bim-query v0.1.2`,
  `bim-publication v0.1.2`, `bim-audit-engine v0.1.3`, `bimdata-write v0.1.3`.

- **E6 — garde catalogue CCH sur le chemin MCP.** `build_catalog` tolère des
  documents illisibles et rend un catalogue vide ; un audit sur ce catalogue rendait
  un verdict faussement « conforme ». Les runners CLI se protégeaient
  (`assert_catalog_usable`, `SystemExit`), **pas le serveur**. Nouveau
  `requirements.catalog.catalog_usable` (non fatal, même critère : refus si
  `properties` **ou** `naming_rules` vide) : `parse_owner_requirements` renvoie un
  `warning` structuré, `full_audit` **refuse** (`ValueError`) plutôt que de produire
  un rapport trompeur. Nouveau `tests/unit/test_catalog_guard_e6.py`.
- **E7 — open data : les pannes ne passent plus pour « aucune donnée ».** Les
  clients `dpe` / `plu` / `georisques` / `ban` avalaient les `RequestException`
  (timeout, 4xx/5xx) et renvoyaient `[]`, avec la source comptée dans `sources_used` :
  un Géorisques down produisait « aucun aléa » dans le livrable. Désormais : `dpe`/`plu`
  laissent **remonter** l'erreur (capturée par l'enricher dans `sources_errors`, source
  **absente** de `sources_used`) ; `georisques` enregistre les échecs **par endpoint**
  (`GeoriskReport.errors`) que l'enricher remonte ; une panne **BAN** est distinguée
  d'une « adresse introuvable » (`sources_errors["ban"]`). Tests dans
  `tests/unit/test_enrichment.py`.

### Fixed (audit profond 2ᵉ passe — Lot 1, Moyens moteur)

- **Dédup parent/sous-classe dans `audit_properties`.** Une même exigence listée
  sur la classe générique du CCH (`IfcWall`) **et** sur une sous-classe
  (`IfcWallStandardCase`) faisait auditer deux fois un élément `IfcWallStandardCase`
  → deux findings **strictement identiques**. Nouveau `_dedup` final (clé
  `element_uuid`/`ifc_type`/`field_path`/`error_type`, ordre préservé). **Changement
  de comptage** (moins de doublons). Nouveau `tests/unit/test_properties_dedup.py`.
- **Audit d'unicité des équipements — thème, classes et casse.** (1) Les défauts
  d'identifiant Tag/Mark étaient rangés dans le thème « Nommage Pièce »
  (`NAMING_SPACE`) → désormais `PROPERTY_MISSING` (manquant) / `PROPERTY_INVALID`
  (doublon), avec `error_type` aligné. (2) Les classes `*Type` (`IfcAirTerminalType`…)
  sont des **définitions de type** partagées, pas des occurrences → exclues (elles
  n'ont pas d'identifiant GMAO par instance). (3) Détection du Pset « Common »
  **insensible à la casse** (`pset_fancommon` était raté). **Changement de comptage**
  (moins de faux positifs sur les types ; findings reclassés hors « Nommage Pièce »).
  Nouveau `tests/unit/test_uniqueness_medium.py`.
- **`IfcProject/LongName` audité sur l'IFC, pas sur le projet plateforme.** La règle
  contrôlait `snap.project["name"]` (nom du projet **BIMData**, saisi dans l'UI, sans
  rapport avec le contenu IFC). Elle lit désormais le `LongName` de l'`IfcProject`
  **à la racine de `structure_tree`** (l'arborescence spatiale de l'IFC) ; arbre
  absent → pas d'audit (au lieu d'un contrôle sur la mauvaise donnée). Nouveau
  `tests/unit/test_ifcproject_source.py`.
- **Robustesse du parseur zones/pièces (`naming_spec_parser`).** (1) Détection de
  l'en-tête du tableau **tolérante** (repli accents + tokens `liste`/`type`/`zone`
  au lieu d'un intitulé exact) — un en-tête légèrement différent ne désactive plus
  silencieusement les contrôles de liste fermée. (2) **Report des cellules mergées**
  PP/PC : openpyxl ne renvoie la valeur que sur la cellule d'ancrage → la
  localisation est reportée sur les lignes suivantes au lieu de retomber à tort sur
  `PP` (zones) ou de perdre la ligne (pièces). Nouveau
  `tests/unit/test_naming_spec_parser_robust.py` (fixtures openpyxl).

### Fixed (audit profond 2ᵉ passe — Lot 1, locateurs E3)

- **Locateurs `IfcName` / `IfcDescription` normalisés.** Le préfixe de classe (abus
  fréquent des annexes V3.7) empêchait tout matching dans `resolve_value` → 100 % de
  faux `PROPERTY_MISSING`. `IfcXxx` désignant un attribut natif est désormais réduit
  à `Xxx`.
- **Locateur `IfcMaterial` résolu depuis l'association.** Le matériau IFC n'est pas
  un attribut plat : bimdata-read l'inline en `material_list`
  (`[{"material": {"name": …}}]`). `resolve_value` ne le lisait pas → 100 % de faux
  `PROPERTY_MISSING`. Nouveau helper `normalizer.material_names` (même forme que les
  helpers `reporting`) ; matériau présent → résolu, absent → `PROPERTY_MISSING`
  **légitime**. **Changement de comptage** (moins de faux positifs). Nouveau
  `tests/unit/test_locators_e3.py`.

### Fixed (audit profond 2ᵉ passe — Lot 1, validation des valeurs)

- **FireRating / AcousticRating sont des codes, pas des numériques.** La clé
  générique `rating` (sous-chaîne de `firerating` / `acousticrating`) dans
  `_NUMERIC_POSITIVE_KEYS` faisait passer `EI30`, `REI 60`, `38 dB` par la
  validation numérique → faux `PROPERTY_TYPE_INVALID`. Nouveau
  `_RATING_STRING_KEYS` traité **avant** le bloc numérique (accepte toute chaîne
  non vide). **Changement de comptage** (moins de faux positifs). Tests dans
  `tests/unit/test_audit_validators.py::TestFireAcousticRatingAreCodes`.

### Fixed (audit profond 2ᵉ passe — Lot 1, famille « nommage »)

- **E4 — `IfcSite` sans `Name` désormais signalé.** La branche « nom manquant »
  n'existait que pour Building/Storey/Zone/Space ; un site sans codification (la
  clé de l'arbre I3F) passait silencieusement. Émet maintenant `NAMING_MISSING`
  (`field_path=IfcSite.Name`, HIGH). **Changement de comptage** (nouveau vrai manquant).
- **E5 — nommage insensible aux accents.** `_check_storey_name` / `_check_room_name`
  et les parseurs d'étages (`naming_spec_parser`, `pdf_parser`) comparaient sans
  replier les diacritiques (`.upper()` seul) → `1ER ÉTAGE` ≠ `1ER ETAGE`,
  `DÉGAGEMENT` ≠ `DEGAGEMENT` → faux `NAMING_NOT_IN_LIST` (ou contrôle désactivé).
  Nouveau helper `domain/text.fold_upper` (repli NFKD centralisé), appliqué **des
  deux côtés** de la comparaison ; libellé d'origine conservé pour l'affichage.
  **Changement de comptage** (moins de faux positifs). Nouveau
  `tests/unit/test_naming_e4_e5.py`.

### Fixed (audit profond 2ᵉ passe — Lot 1 « le moteur dit vrai »)

- **C1 — faux positif « quantité manquante » sur toute pièce conforme.**
  `audit_spatial` lisait la surface via `resolve_value(sp, "BaseQuantities", "NetFloorArea")` :
  un locateur sans `/` ni préfixe `Pset` ne matchait aucune étape de routage et renvoyait
  toujours `None`, faisant émettre `SPATIAL_MISSING_QUANTITY` sur **chaque** `IfcSpace`
  possédant pourtant sa surface en `BaseQuantities`. Corrigé en passant par le locateur
  composite `BaseQuantities/NetFloorArea` (route vers `get_quantity_with_fallback`, repli
  ArchiCAD inclus). **Changement de comptage** : les rapports perdent ces faux positifs du
  thème « Quantités » ; le finding légitime (pièce réellement sans quantité) est conservé.
  Nouveau `tests/unit/test_spatial_quantity.py` (cas positif *et* négatif).
- **E1 — les exigences `kind="quantity"` du format 2026 sont enfin auditées.**
  `audit_properties` filtrait `kind == "property"` : les quantités (`BaseQuantities`,
  toutes classes — murs, dalles, pièces…) n'étaient **jamais** vérifiées. Elles le sont
  désormais (thème « Quantités », `SPATIAL_MISSING_QUANTITY`, sévérité MEDIUM).
  Réconciliation « spatial cède à properties » : le contrôle IfcSpace câblé de
  `audit_spatial` devient un **repli** actif uniquement quand le catalogue n'a **pas**
  d'exigence quantité sur `IfcSpace` (ancien format V3.x) → pas de double comptage.
  **Changement de comptage** (plus de vrais manquants 2026). Nouveau
  `tests/unit/test_quantity_audit_e1.py`.

### Changed (refactor PR4 — factorisation)

- **Dédup / factorisation** (`docs/instruct-refactor-pr-series.md` §PR4), goldens +
  payloads **inchangés**. (4a) Les gardes des runners (`assert_outside_repo` ×4,
  garde catalogue ×2) déménagent dans `audit_bim/security/guards.py` (**module
  produit**, pas `scripts/_guards.py` — les runners sont chargés par chemin dans les
  tests) ; messages contextualisés via `context=`. Tests des gardes réunis dans
  `tests/unit/test_guards.py`. (4b) Squelette commun `actions/_apply_runtime.py`
  (`run_apply` + `ApplyOutcome`) portant contrôle de `kind` → cible → `validate_target`
  → journal → `ActionResult` : chaque planner (`bcf`/`smartview`/`doe`/`classification`)
  ne garde que **son exécuteur** d'items — payloads de refus/résultat **byte-identiques**
  (un futur 5ᵉ planner ne peut plus oublier la garde). (4c) `build_catalog` **mémoïsé**
  sur `(chemin résolu, mtime, taille)` des 3 sources : « preview puis audit » économise
  un second parse ; fichier modifié → reconstruction ; source manquante → pas de cache.
  (4d) Helper `suggestions_map` unique dans `classifier/` — `word_report` et
  `xlsx_annex` consomment le même (fin du doublon byte-à-byte).

### Security (refactor PR3 — durcissement transport)

- **Défaut secure-by-transport passé en fail-closed** (`docs/instruct-refactor-pr-series.md`
  §PR3). **3 changements de comportement, tous listés** : (3a) un transport **non
  déclaré** (`None` : montage ASGI custom, `fastmcp run`) est désormais traité comme
  **réseau** → écritures **et** `access_token` en paramètre **refusés** par défaut
  (au lieu de permissifs). Les entrypoints locaux légitimes se **déclarent
  explicitement** (`__main__` stdio ; `cli.py` + les 3 runners de `scripts/` en mode
  `"script"` ; fixture de tests autouse). Précédence `AUDIT_BIM_ALLOW_WRITES`
  inchangée (le flag explicite gagne toujours). (3b) `AUDIT_INPUT_DIR` devient
  **obligatoire pour tout transport réseau** (refus de démarrer), indépendamment de la
  clé service — seul opt-out `AUDIT_BIM_ALLOW_UNBOUNDED_INPUTS=true`. (3c)
  `apply_classifications_from_xlsx` **reconstruit sur le contrat prepare→apply** :
  lecture xlsx (sandbox) → **plan scellé** → refus sans `confirm=True` → `validate_target`
  → apply → journal ; le paramètre `dry_run` **disparaît** (l'appel sans `confirm` EST
  le dry-run). (3d) `.env.example` complété des 9 variables de sécurité, `SECURITY.md`
  mis à jour (tableau transport → posture). Tests : transport `None` → refus
  écritures/token ; mode `script` → autorisé ; HTTP sans `AUDIT_INPUT_DIR` → refus
  démarrage ; xlsx-apply sans `confirm` → `refused` ; xlsx-apply complet → entrée
  journal. Dry-run A1 rejoué vert (runners en mode `script`).

### Changed (refactor PR2 — mcp/app.py + éclatement de server.py)

- **Enregistrement explicite des tools + éclatement de `server.py`**
  (`docs/instruct-refactor-pr-series.md` §PR2). (2a) L'instance `FastMCP`, les
  middlewares et l'état de session vivent dans `mcp/app.py` (socle **sans tools**) ;
  tous les modules de tools importent `from .app import mcp` ; l'enregistrement passe
  par une fonction **explicite** `register_all()` (ordre déclaré, appelée par
  `__main__`) — le bloc d'import à effet de bord en fin de `server.py` et **tous** les
  `noqa: E402` disparaissent. (2b) Les 20 tools de `server.py` (1878 l.) sont répartis
  **par nature** : `tools_session` (cible/contexte/config), `tools_audit` (audit +
  findings), `tools_reporting` (livrables), `tools_actions` (+`apply_classifications_from_xlsx`) ;
  les helpers de phase/contexte vont dans `mcp/phase.py`. `server.py` devient un mince
  module **compat** (prompt + `main` + ré-exports dépréciés). (2c) `full_audit`
  (356 l.) est décomposé en **étapes nommées testables** (`_fa_resolve_target_and_context`,
  `_fa_resolve_push_mode`, `_fa_prepare_catalog`, `_fa_finalize_target`,
  `_fa_extract_snapshot`, `_fa_assert_expected_model`, `_fa_write_deliverables`,
  `_fa_prepare_publication`, `_fa_write_findings_json`, `_fa_build_payload`), le tool
  n'étant plus qu'un orchestrateur court. **Contrat gelé** : inventaire **49 tools**
  identique, signature + payload de `full_audit` byte-identiques (clients + tests),
  `python -m audit_bim.mcp` inchangé. Étapes testées unitairement
  (`tests/unit/test_full_audit_steps.py`).

### Changed (refactor PR1 — cycles de couche)

- **3 cycles d'import cassés** (`docs/instruct-refactor-pr-series.md` §PR1) : (1a)
  `SEVERITY_COLORS` (palette feux tricolores, convention métier) déménage de
  `reporting/theming` vers `audit/findings`, à côté de l'enum `Severity` — `theming`
  la **ré-exporte** (import descendant légal) : `word_report`/`xlsx_annex`/`avp_i3f`
  inchangés, tokens de charte `BIMDATA_*` intouchés ; (1b) `audit/ifc_hierarchy.py`
  déménage vers `domain/ifc_taxonomy.py` (taxonomie IFC, pas de l'audit — pas de shim) ;
  (1c) `ProjectAddress` déménage vers `domain/address.py`, `doe` l'importe depuis
  `domain` (plus depuis `enrichment`) → `enrichment → doe` redevient unidirectionnel,
  l'import paresseux « éviter le cycle » promu en import normal. **Verrou
  architectural** `tests/unit/test_architecture.py` (ast) fige les règles de couches.
  Additif : goldens de parité publication inchangés.

- **Démarrage serveur/CLI allégé** : `matplotlib` (~330 ms) et `openpyxl`
  (~200 ms) ne sont plus importés qu'à l'usage (génération Word / parsing
  xlsx), plus au chargement du module. Le patch `patch_openpyxl` est appliqué
  explicitement par chaque consommateur (`avp_i3f`, `avp_sources`) au lieu de
  reposer sur un effet de bord d'import.
- **Matcher DOE** : la liste des noms candidats (invariante) est construite une
  fois hors de la boucle des enregistrements.
- **README** : arbre `mcp/` corrigé (le « FastMCP + 10 tools » datait d'avant
  `tools_actions`/`tools_query`) ; `docs/mcp_tools.md` re-synchronisé (49 tools,
  ajout des 4 manquants : `generate_avp_i3f_pack`, `import_preliminary_findings`,
  `prepare_smart_view_from_filter_plan`, `show_filtered_objects_in_viewer`).

### Removed (audit technique CTO — code mort vérifié sans référence)

- **`requirements.txt`** : dérive dangereuse vs `pyproject.toml`
  (`pypdf>=4.0` alors que le projet impose `>=6.9.1` pour couverture CVE ;
  `fastmcp>=0.4` vs `>=3.0`). Aucun consommateur (la CI exporte depuis
  `uv.lock`) — `pyproject.toml` + `uv.lock` font foi.
- **`audit_bim/reporting/korhus_brand.py`** : shim de compat sans plus aucun
  import interne ni externe connu depuis la migration charte BIMData (v0.4.x).
- Helpers privés morts : `word_report._para_or_na`,
  `word_report._generate_recommendations` (supersédé par
  `_recommendations_by_priority`), `context._iter_non_empty`,
  `write_journal.journal_path_from_env`, dataclass `avp_sources.TabularSource`,
  constantes `data_spec_parser.COL_DEFINITION`/`COL_PHASES`, et 12 des 18 alias
  de charte dépréciés de `theming.py` (aucune référence, tests compris).
- `.gitignore` durci (`*.key`, `*.pem`, `.env.*`).

## [0.8.0] - 2026-07-07

Jalon : **`field_path` généralisé** aux findings non-zone (grammaire gelée + verrou
générique) et **dette override uv soldée** (les 5 packages first-party ré-taggés sous
tags immuables pinnant `bim-core v0.1.1`, plus aucun `override-dependencies`). Pins :
`bim-core v0.1.1`, `bimdata-read v0.1.4`, `bimdata-write v0.1.2`, `bim-query v0.1.1`,
`bim-publication v0.1.1`, `bim-audit-engine v0.1.2`.

### Added

- **`field_path` généralisé aux findings non-zone** — le champ structuré
  `Finding.field_path` (jusqu'ici émis sur les seules zones) est désormais émis par
  **6 familles** de règles (`naming`, `lists`, `uniqueness`, `properties`, `spatial`)
  selon une **grammaire gelée** : `<IfcClass>.<Attribut>` / `<IfcClass>.<Pset>.<Prop>` /
  `<IfcClass>.<Qto>.<Quantity>` (dérivé du **locateur technique**, jamais du libellé
  humain). Les défauts sans champ IFC unique restent `None` : classification + orphelin
  spatial (liste blanche par `error_type`), et findings de **couverture** (sans objet,
  `element_uuid is None`). Un **verrou générique** (`tests/unit/test_field_path_lock.py`)
  rend impossible l'ajout d'une règle émettant un `field_path` mal formé, un premier
  segment ≠ classe IFC réelle de l'objet, ou un `None` injustifié. Findings importés
  exclus par **marqueur structuré de provenance** (`is_imported_finding`). Émission
  seule : **aucun** consommateur spéculatif. Scope gelé : `docs/scope-field-path.md`.

### Changed

- **Overrides uv retirés (dette cross-repo soldée)** — les 5 packages first-party
  transitifs ont été alignés sous **nouveaux tags immuables** pinnant `bim-core
  v0.1.1` : `bim-query v0.1.1`, `bim-publication v0.1.1`, `bimdata-read v0.1.4`,
  `bim-audit-engine v0.1.2` (+ correction du wording `result.py` « immuable »),
  `bimdata-write v0.1.2` (+ `bimdata-read v0.1.4`). audit-bim ré-épingle les 5 et
  **supprime les deux `override-dependencies`** (`bim-core` + `bimdata-read`) :
  `uv lock` résout désormais le graphe **sans forçage**. Vérifié : `uv lock
  --check` propre, **balayage d'intégrité des 7 tags** (rev du lock == tag distant
  peelé, réflexe post-incident tag déplacé), suite 1084.

Jalon : **replay A1 industrialisé** (publication BCF / Smart Views `prepare → review
→ apply` avec verdict machine + `--write` réel prouvé et auto-purgé sur maquette
jetable), acceptation du rapport Word AVP, fiabilisation `field_path` des zones, et
durcissement du wheel de release. Pins first-party : `bimdata-read v0.1.3`,
`bimdata-write v0.1.1` (+ `bim-core v0.1.1`).

### Fixed

- **Replay A1 — re-lecture Smart Views + tag `bimdata-read` déplacé** — la
  validation `--write` réelle a attrapé que `list_smart_views()` renvoyait `0` : le
  correctif « côté serveur `?format=` » avait été tagué `bimdata-read-v0.1.2` mais
  **le tag a été déplacé après publication** (`497c6058` → `be43575`), et le lock
  restait épinglé sur le commit *pré-correctif* → `uv sync` réinstallait le code
  cassé. Remédiation : re-publication propre sous **`bimdata-read v0.1.3`** (tag
  immuable ; v0.1.2 proscrite), audit-bim ré-épinglé v0.1.2 → **v0.1.3** (sources +
  override + lock + CI/release). `--write` **propre en un seul run : PASS** (apply +
  journal + re-lecture API 1/1 + purge → 0). `delete_bcf_topic` **et**
  `delete_smart_view` validés contre l'API réelle. Voir `docs/validation-a1-replay.md`.

### Added

- **Replay A1 — purge automatique (`create → verify → purge`)** — `bimdata-write`
  bumpé à **v0.1.1** (`delete_bcf_topic` / `delete_smart_view`, transport `DELETE`
  authentifié). Le `--write` du runner **supprime les objets qu'il vient de créer**
  après les avoir prouvés (3 niveaux), puis une **re-lecture indépendante** confirme
  qu'il ne reste `0` objet au préfixe daté de ce run → `--write` **déterministe en
  un seul run**, sans nettoyage manuel. Sélection **bornée au préfixe daté** (helper
  pur `select_purge_guids`, testé hors réseau) ; `--keep` conserve les objets pour
  l'inspection visuelle périodique 5b ; une purge incomplète bascule le verdict en
  `FAIL`. Fait évoluer la décision A du scope (auto-delete, autrefois hors v1).

- **Replay A1 — validation `--write` réelle + étape 8** — `bimdata-read` bumpé à
  **v0.1.2** (`list_bcf_topics`/`list_smart_views`, filtrage `?format` côté
  serveur) ; le `--write` du runner vérifie l'écriture à **3 niveaux** (rapport
  d'apply + journal + re-lecture API indépendante). Validation réelle sur Dieppe
  **PASS** (1 BCF + 1 Smart View), qui a attrapé et fait corriger un vrai écart de
  lecture des Smart Views. La re-lecture indépendante ramène le hand-off 5b à un
  **contrôle périodique**. Voir `docs/validation-a1-replay.md`.

- **Replay A1 industrialisé** (`scripts/a1_replay/run_replay.py`) — rejoue la
  publication BCF / Smart Views (`prepare → review → apply`) avec un verdict
  machine, symétrique de l'acceptation AVP. **Dry-run par défaut** (aucune
  écriture) ; `--write` manuel **uniquement** sur le modèle jetable
  (`REPLAY_WRITE_MODEL_ID`). Helpers purs partagés `assert_write_target` /
  `inspect_plan`, garde-fou négatif rejoué (`confirm=False` → refus), compte
  déterministe (1 topic + 1 Smart View). CI hors-ligne : les **4 refus** testés
  (`tests/unit/test_a1_replay_runner.py`). Dry-run réel **PASS** sur Dieppe.
  Scope : `docs/scope-a1-replay.md`.

### Changed

- **Classification Name/ObjectType des zones fiabilisée par un champ structuré**
  (dette résolue) — `bim-core` **0.1.1** expose un champ neutre `field_path` sur
  `Finding` (ex. `"IfcZone.ObjectType"`). `rules/naming.py` l'émet sur les 4 sites
  zone, et `_zone_finding_kind` s'appuie dessus **en priorité** (heuristique de
  libellé conservée en simple repli). Un reformulage du wording des règles ne peut
  plus fausser silencieusement la grille de contrôle AVP. Pin `bim-core` bumpé
  `v0.1.0 → v0.1.1` (rétro-compatible : `field_path` optionnel, défaut `None` ;
  builders/goldens de publication inchangés).

### Added

- **Acceptation du rapport Word AVP** (6ᵉ livrable) — un helper unique
  `inspect_word_report` (partagé runner ↔ tests) vérifie : contenu non vide
  (≥ 10 paragraphes **et** ≥ 10 cellules significatives hors `NOT_AVAILABLE`),
  sections **1 à 9**, métadonnées projet/phase (le **vrai** nom BIMData, jamais le
  bouchon), charte BIMData sans KORHUS. Le runner réseau échoue si le rapport Word
  n'est pas conforme (code 0 = **5 annexes xlsx ET rapport Word**). Preuve réelle :
  `docs/validation-avp-word-post-0.6.0.md`.

### Changed

- **Release CI** : le workflow installe désormais le wheel construit dans un
  **venv vierge** (préinstall des 7 packages tagués + `pip install <wheel>`),
  vérifie `pip check`, importe `audit_bim` et exécute `audit-bim --help` avant de
  publier la GitHub Release — un wheel qui ne s'installe/importe pas bloque la
  release.

### Fixed

- **Runner d'acceptation — match des intitulés de sections Word réellement
  insensible aux accents** : le contrôle promettait « casse/accents » mais
  n'appliquait que `casefold()` (casse seule). Normalisation NFKD (suppression
  des diacritiques) + casse via `_norm_title`, testée
  (`test_word_accepts_unaccented_titles`). Relevé par l'audit de clôture du
  jalon : `docs/audit-avp-acceptance-instruct-field-path.md` (qui porte aussi
  l'instruction `field_path` — exécutée via `bim-core-v0.1.1` + #73 — et le
  registre de dette ouvert : retrait de l'override uv, wording « immuable »,
  CI bim-core).

## [0.6.0] - 2026-07-06

### Added

- **Acceptation automatisée du pack AVP** — le pack de livrables AVP I3F est
  désormais accepté automatiquement, à deux niveaux :
  - **test CI hors-ligne** (`tests/unit/test_avp_pack_acceptance.py`) : sur un
    snapshot représentatif, les **5 annexes xlsx** sont non vides, habillées de
    la **charte BIMData** (wordmark `BIMDATA`, primaire `#2F374A`, police
    `Roboto`), sans l'ancienne charte KORHUS ; exactitude métier de la grille de
    contrôle vérifiée **jusqu'aux valeurs de cellules Excel** ;
  - **runner réseau réel** (`scripts/avp_acceptance/run_acceptance.py`,
    read-only) : verdict PASS/FAIL sur une vraie maquette ; gardes testées
    (document I3F absent / catalogue vide / écriture hors dépôt).

### Changed

- **QA gate anti-livrable vide étendue à la 5ᵉ annexe (« Contrôle »)** — la
  génération du pack refuse (`AvpQaError`) si la grille de contrôle ne porte
  aucun point de contrôle réel (comptés **sous** son titre, hors entête / légende
  / `NOT_AVAILABLE`, via un compteur dédié `_count_controle_rows`). Auparavant
  seules 4 annexes étaient gardées.
- **Grille de contrôle générée depuis l'`AuditResult`** quand aucune source I3F
  « Contrôle » n'est fournie (points de contrôle réels : nommage zones/pièces,
  ObjectType, matériaux, avec conformité mesurée).

### Fixed

- **Contrôles Zone « Nommage » et « ObjectType » séparés** — ils étaient agrégés
  par thème (`NAMING_ZONE`), déclarant une zone au Name invalide non conforme
  dans les deux contrôles. Ils sont désormais comptés sur des ensembles de
  findings disjoints.
- **Lecture des matériaux** — le contrôle « absence de matériau » lisait la clé
  `materials` alors que `bimdata-read` produit `material_list`
  (`[{"material": {"name": …}}]`), déclarant tous les éléments sans matériau. Il
  lit désormais `material_list` (repli `materials`) en exigeant un vrai nom, et
  calcule `conforme` / `conforme_ratio`.

### Notes

- Acceptation réseau réelle **PASS** sur `250613_MN_BAT.ifc` (voir
  `docs/validation-avp-pack-0.6.0.md`). Aucune donnée client versionnée.
- **Dette connue (non bloquante)** : la classification d'un finding de nommage de
  zone en Name vs ObjectType s'appuie partiellement sur le texte du finding →
  prévoir à terme un champ structuré `control_id` / `field_path` sur `Finding`.

## [0.5.2] - 2026-07-05

**Remplace v0.5.1** : le wheel/sdist v0.5.1 est **antérieur** à l'adoption du
package `bim-audit-engine` (#63) et à la façade du moteur (#64). **Utiliser
v0.5.2** pour un wheel cohérent avec le master.

### Changed

- **Moteur d'audit extrait vers `bim-audit-engine`** (7ᵉ package first-party) —
  `audit_bim.audit.engine` devient une **façade mince** sur le cœur générique
  `bim-audit-engine` (protocole `Rule`, `run_audit` à règles injectables,
  `AuditResult` générique, tri déterministe) :
  - `AuditResult` est **ré-exporté à l'identique** depuis `bim_audit_engine`
    (`audit_bim.audit.engine.AuditResult is bim_audit_engine.AuditResult`) —
    champs, méthodes et dump JSON inchangés (#64) ;
  - `run_audit(snap, catalog, phase)` conserve sa signature et injecte les
    `I3F_RULES` I3F dans le moteur générique — **parité par équivalence** ;
  - `audit_naming` accepte désormais `phase` (ignoré) pour respecter le
    protocole `Rule` ;
  - adoption infra (dépendance + `[tool.uv.sources]` tag
    `bim-audit-engine-v0.1.1` + `uv.lock` + préinstall CI/release) (#63).
  - Restent **I3F, inchangés** : `RequirementsCatalog`, `BIMPhase`, les 6 règles
    concrètes, `validators`/`ifc_hierarchy`/`normalizer`, `preliminary`.

### Notes

- **Parité prouvée sur maquette réelle** (read-only, sans publication BIMData) :
  sur `250613_MN_BAT.ifc` (projet I3F, 10 549 éléments) avec le catalogue CCH 3.6
  réel, l'ancien moteur (`65ac0c9`) et la façade produisent **49 798 findings
  strictement identiques** (mêmes `Finding.model_dump()`, même **ordre**, même
  `summary()` et mêmes agrégats). Voir
  `docs/validation-parity-bim-audit-engine.md`.

## [0.5.1] - 2026-07-05

**Remplace v0.5.0** : le wheel/sdist v0.5.0 (commit `9cc2b9d`) est **antérieur**
au correctif CLI (#59) et embarque encore les écritures directes de la CLI.
**Utiliser v0.5.1.**

### Changed

- **CLI `audit-bim` : préparation de plans uniquement** (#59) — la CLI n'écrit
  plus jamais dans BIMData. `--push bcf|smartview|both` **prépare** des `WritePlan`
  scellés (`prepare_bcf`/`prepare_smart_views` + `save_plan`) ; la publication se
  fait via le serveur MCP `apply_*(confirm=True)` après revue. La **cible** des
  plans provient désormais du **client effectif** (`client.cloud_id/project_id/
  model_id`), pas des arguments bruts.
- **CI/CD** : `actions/setup-python@v6` (#3), `actions/upload-artifact@v7` (#4),
  `actions/download-artifact@v8` (#2).

### Removed

- Builders d'écriture directe `push_bcf_topics` / `push_smart_views` (devenus
  morts après #59) — les modules `bcf.builder` / `smartview.builder` sont de
  pures façades `build_*` au-dessus de `bim-publication`.

### Added

- Test CLI de non-écriture (`test_cli_no_write.py`) : client mutatif qui **échoue
  au moindre appel** d'écriture + vérification de la cible issue du client.

## [0.5.0] - 2026-07-05

### Removed

- **BREAKING** — suppression des **5 tools MCP hérités** et de leurs chemins
  `legacy_execute=True` (push direct). Migrer vers le workflow
  `list → (accept/reject) → prepare → apply` :
  - `suggest_classifications` → `list_classification_suggestions` ;
  - `create_bcf_topics` → `prepare_bcf_topics` → `apply_bcf_topics(confirm=True)` ;
  - `create_smart_views` → `prepare_smart_views_plan` →
    `apply_smart_views_plan(confirm=True)` ;
  - `apply_suggested_classifications` → `list_classification_suggestions` →
    `update_suggestion_status` → `prepare_classification_update_plan` →
    `apply_classification_update_plan(confirm=True)` ;
  - `doe_enrich_model` → `match_doe_to_ifc` → `prepare_doe_enrichment_plan` →
    `apply_doe_enrichment_plan(confirm=True)`.
  Le module `audit_bim/mcp/tools_legacy.py` est supprimé ; `DEPRECATIONS` est
  vidé (infrastructure conservée). Les builders `push_bcf_topics` /
  `push_smart_views` restent (utilisés par `full_audit`). Un test d'inventaire
  (`test_mcp_inventory.py`) atteste l'absence des 5 tools du registre MCP.

### Added

#### Pack de livrables AVP I3F (`generate_avp_i3f_pack` / `write_avp_i3f_report_pack`)

- Nouveau livrable dédié reproduisant, sous **charte BIMData**, le jeu I3F
  d'une opération AVP (Tarare 0546L) : 5 Excel (Contrôle Maquettes, SHAB,
  Zones/Espaces, Enveloppe + ratio FAC/SHAB & Seuil 3F 2026, Menuiseries)
  + rapport consolidé **Analyse BIM AVP** (.docx, + .pdf best-effort).
- **Hybride** : données natives de l'audit BIMData (`_State.result`) +
  lecture des .xlsx sources I3F pour les colonnes d'outils externes
  (Solibri/ArchiCAD/écarts). **Ne jamais inventer** : donnée absente →
  « Information non disponible dans les documents fournis. ».
- Réutilise l'infra existante (`xlsx_annex._build_formats`/`write_safe`,
  helpers `word_report`, `theming`/`bimdata_brand`) — pas de stack
  parallèle. Nouveaux modules `reporting/avp_sources.py` (lecteurs),
  `reporting/avp_i3f.py` (builders/orchestration), `reporting/pdf_export.py`
  (conversion .docx→.pdf best-effort via LibreOffice, `AUDIT_BIM_SOFFICE`).
- Fidélité « tables à plat » (mêmes onglets/colonnes/ordre/unités/vocabulaire) :
  parsing structure-aware des stats de contrôle (nommage « Noms (nbre) » vs
  matériau), **préservation des onglets** pivot/synthèse des exports
  (`Feuil1`/`Feuil2` + `TDB…`), noms de fichiers **repris des sources**
  (traçabilité), seuil 3F **jamais inventé** (NOT_AVAILABLE si absent),
  consolidé enrichi (données d'entrée, usages 3F, grille, annexes stats).
  Reproduction des **grilles détaillées** des onglets de contrôle,
  **synthèse d'audit BIMData réelle** (répartition CRITICAL→INFO, top
  thèmes, quantités manquantes), grille de contrôle Word en **paysage**,
  préservation de **tous** les onglets source (y compris vides), et
  **métadonnées opérationnelles** du contrôle (`usages_bim`,
  `nombre_logements`, `temoin_virtuel`, `date_controle`, `auteur_controle`).
- Tests : structure d'onglets, ordre des en-têtes, branding BIMData
  (`#2F374A`/`#F9C72C`/Roboto/bannière), **absence de l'ancienne charte**,
  never-invent, sections du consolidé, PDF best-effort.

#### Extraction AVP source-first, snapshot en repli + QA gate anti-livrable vide

- Nouveau module `reporting/avp_snapshot.py` : si les fichiers sources I3F
  sont **absents**, les exports SHAB, Zones/Espaces, Enveloppe et Menuiseries
  sont générés depuis `AuditResult.snapshot` (les sources I3F priment quand
  elles existent). Fini les annexes réduites au seul bandeau.
- **Enveloppe** : sélection des murs par **layer** normalisé
  (« MURS - Extérieurs périphériques.Exnd », tolérance casse/accents/espaces),
  classes `IfcWall` + `IfcWallStandardCase`. **`IfcCurtainWall` exclu**
  (façade vitrée comptée en menuiseries — décision documentée). Surface par
  ordre `NetSideArea` → `GrossSideArea` → `NetArea` → `GrossArea` puis repli
  propriété **« Superficie calculée »** (accent-insensible, tous Psets). La
  **source de la valeur** (BaseQuantities vs Superficie calculée) est tracée
  dans une colonne dédiée.
- **Espaces / zones** : libellé = `LongName`, sinon `Name` (repli si vide) ;
  surface `NetFloorArea` → `GrossFloorArea` → `NetArea` → `GrossArea` puis
  « Superficie calculée ». Zone sans surface propre → **somme des espaces
  rattachés** si la relation zone/espace est disponible. L'export **SHAB
  maquette** (et « Espaces ») ajoute les colonnes **Zone** et **Étage** de
  chaque pièce, **multi-valuées** (séparateur « / ») pour couvrir les
  **duplex** — zone traversant plusieurs niveaux ou espace rattaché à
  plusieurs zones d'étage. L'export **Zones et Espaces** a désormais pour
  **1er onglet la liste des IfcZone** (colonnes *Zone (IfcZone)*, *Libellé*,
  *Étage(s)* — union des étages des pièces, duplex géré —, *Nombre de
  pièces*, *Surface*), suivi de l'onglet Espaces. Cet enrichissement maquette
  (IfcZone + étage) est **ajouté même quand des sources I3F sont fournies**
  (après les onglets source fidèles), pour que les zones et étages du modèle
  soient toujours visibles.
- **QA gate post-génération** : chaque annexe est rouverte et ses lignes
  métier comptées. Si SHAB, Zones/Espaces ou Enveloppe sortent **sans ligne**
  alors que le snapshot contient des espaces/murs/zones exploitables, le tool
  `generate_avp_i3f_pack` renvoie `{status: "error", error:
  "empty_deliverable", empty_deliverables: [...]}` (exception `AvpQaError`) —
  jamais un fichier client vide.

#### Phase : question unique (loi MOP / phase BIM) + nommage I3F des livrables

- **Une seule question de phase** — plus de doublon « phase loi MOP » /
  « phase BIM ». La phase confirmée est l'**unique source de vérité** et
  alimente à la fois l'audit, le rapport Word et le pack AVP. La question
  affiche une **aide de lecture loi MOP / mission MOE** dans le même champ
  (APS…GESTION) — pas de second champ.
- **Proposition automatique + validation explicite** : si une phase est
  déclarée dans l'IFC / les métadonnées BIMData, elle est proposée comme
  valeur par défaut (`suggested_value`) et confirmée explicitement. Une
  phase non reconnue (APD, ACT, VISA, DET…) est **rapprochée** de la phase
  d'audit (APD→AVP, ACT/VISA/DET→EXE, ESQ→APS, AOR→DOE) à confirmer ou
  corriger. `full_audit` ne défaute plus silencieusement sur `PRO` : sans
  phase explicite, il demande confirmation (sauf `confirm_context=True`).
- **Nommage documentaire I3F** des livrables du pack AVP, **généré à partir
  de données projet confirmées** :
  `YYMMDD <NomProjet> <CodeProjet> <Phase> - <TypeLivrable>.<ext>` où
  `YYMMDD` est la **date de génération**. Le nom du projet privilégie
  l'**entête « Projet » du contrôle I3F** (source livrable autoritaire) sur
  un `project.name` BIMData potentiellement générique (ex. « I3F »), le code
  (ESI) vient du contrôle maquettes I3F, la phase est la phase d'audit
  confirmée. Nom, code **ou phase** introuvable → `generate_avp_i3f_pack`
  renvoie `needs_context` (la phase n'est **jamais** défautée silencieusement
  sur « AVP »). Les noms ne reprennent plus le basename des sources ; le
  writer bas niveau n'a plus de défauts d'identité client (`Tarare`/`0546L`).
- `project_context_questions` : question de phase **unique** alignée sur le
  contrat (clé `project_phase`, aide loi MOP, détection IFC + rapprochement),
  sans suggestion « PRO » codée en dur ni clé divergente.

#### Dialogue de contexte : adresse suggérée + description projet

- `full_audit` et `generate_word_report` **proposent l'adresse** extraite
  de la maquette (`IfcBuilding.BuildingAddress` / `IfcSite.SiteAddress`,
  via `resolve_project_address`) dans la question `project_address`
  (`suggested_value`) — l'utilisateur valide ou corrige au lieu de la
  saisir à froid. Best-effort : sans adresse exploitable, question posée
  sans suggestion.
- Nouveau paramètre **`project_description`** sur `full_audit` et
  `generate_word_report`, propagé au contexte (`merge_user_context`) et
  **rendu dans le rapport Word** (section « Maquette auditée » →
  *Description du projet*). La description est **toujours demandée** quand un
  snapshot est disponible (jamais reprise en silence) : la question propose
  la description maquette (`project.description`) en `suggested_value`, à
  **valider ou corriger** par l'utilisateur. `confirm_context=True` court-
  circuite.
- Pack AVP : l'**auteur du contrôle est demandé explicitement**
  (`needs_context`) si ni `auteur_controle` ni `auditor` ne sont fournis —
  plus de « AMO BIM » générique par défaut, sauf `confirm_context=True`.
  `auteur_controle` prime sur `auditor`.

#### Sélection d'objets BIM enrichie (`filter_bim_objects`)

- Nouveaux filtres **structurels** sur `ObjectFilter` : quantités
  (`has_base_quantities`, `has_quantity`, `missing_quantity` par nom de
  BaseQuantity) et **nommage** (`name_contains`, `name_regex` sur
  Name/LongName, regex validée à la construction).
- Nouvelle voie **pilotée par l'audit** sur l'outil `filter_bim_objects` :
  `with_finding_themes` / `with_finding_error_types` /
  `with_finding_severities` — intersection avec les anomalies de
  `run_audit_tool` (ex. « quantités manquantes » =
  `with_finding_error_types=["spatial_missing_quantity"]`). Valeurs
  **validées contre les enums** `Theme` / `ErrorType` / `Severity`
  (valeur inconnue → `ValueError`).
- Paramètre `include_spatial` pour sélectionner les **pièces** (`IfcSpace`,
  exclues par défaut) — **auto-activé** dès qu'un `ifc_types` spatial est
  ciblé ou qu'un filtre audit est utilisé (évite un piège d'usage : les
  anomalies `spatial_missing_quantity` portent sur des `IfcSpace`).
- La réponse ajoute `uuids` (jeu de sélection **complet** après filtres,
  pré-pagination) ; `total` documenté comme cardinal post-filtres /
  pré-pagination. Sur fallback disque, `uuids` est compacté en aperçu +
  `uuids_count` / `uuids_truncated` (le JSON complet est dans `items_path`).
  Additif, rétro-compatible.

### Changed

#### Rebrand des livrables vers la charte BIMData

- Les rapports Word + Excel suivent désormais la **charte BIMData —
  Brand Guidelines 2022 v1.0** (et non plus Korhus.ai) :
  - couverture bleu ardoise `#2F374A`, accent jaune `#F9C72C`, bleu royal
    `#3375DD`, police Roboto / Arial ;
  - wordmark de repli « BIMDATA » ; supertitles Excel « BIMDATA — … » ;
  - palette catégorielle des graphes alignée sur les teintes BIMData.
- Nouveau module `audit_bim.reporting.bimdata_brand` (résolution des
  logos via `BIMDATA_BRAND_KIT_DIR`, fallback `KORHUS_BRAND_KIT_DIR` et
  dossier sibling `bimdata_brand_kit/`). L'ancien module
  `korhus_brand` devient un shim de compatibilité.
- `theming.py` : tokens canoniques `BIMDATA_*` ; les constantes
  `KORHUS_*` et `I3F_*` deviennent des alias **dépréciés** pointant sur
  les valeurs BIMData (rétro-compatibilité préservée).
- Charte éditoriale formalisée dans
  `audit_bim/reporting/BRAND_GUIDELINES.md` (logo, typographie, couleurs,
  mise en page, QA avant publication), livrée avec le package et
  référencée depuis `theming.py`. Le code ne garde que les tokens
  exécutables — pas de duplication de la charte.

#### Refonte du rapport Word — modèle « rapport d'audit de conformité de la maquette numérique »

- Le rapport Word (`write_word_report`) suit désormais la structure
  normalisée d'un rapport d'audit de conformité :
  1. Page de garde (Titre, Projet, Maquette auditée, Version, Date,
     Auteur, Référence du CCBIM utilisé) ;
  2. Synthèse exécutive (objectif, niveau de conformité, points de
     vigilance, **décision** Acceptée / Acceptée sous réserve / Refusée,
     tableau d'indicateurs) ;
  3. Périmètre de l'audit (documents de référence + maquette auditée :
     discipline, auteur, date, logiciel, version IFC) ;
  4. Méthodologie (familles de contrôles réalisés) ;
  5. Résultats globaux (synthèse par domaine : Conforme / Avertissement /
     Non conforme) ;
  6. Résultats détaillés (6.1 Structure, 6.2 Qualité des données,
     6.3 Classification, 6.4 Conventions de nommage, 6.5 Contrôles
     géométriques, 6.6 Cohérence métier, 6.7 Détection des conflits) ;
  7. Liste des non-conformités (tableau ID / Règle / Objet / Gravité /
     Commentaire / Action) ;
  8. Recommandations classées par priorité (Critique / Majeure / Mineure) ;
  9. Conclusion (conformité globale, points bloquants, décision finale) ;
  10. Annexes.
- Les familles de contrôles non couvertes par l'audit automatisé
  (géométrie fine, cohérence métier détaillée, détection de conflits)
  sont **explicitement signalées comme hors périmètre** — jamais
  présentées comme conformes (principe « on n'invente jamais »).

### Added

#### Persona AMO BIM : dialogue en français + liens vers les rapports

- Consigne explicite de mener **tout le dialogue en français**.
- Consigne de proposer systématiquement un **lien cliquable** (`file://`)
  pour ouvrir les rapports Word (`.docx`) et Excel (`.xlsx`) générés.

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
