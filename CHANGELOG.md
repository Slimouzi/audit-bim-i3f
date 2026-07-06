# Changelog

Toutes les évolutions notables de ce projet sont consignées dans ce fichier.

Format basé sur [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/), versioning
[SemVer](https://semver.org/lang/fr/).

## [Unreleased]

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
