# Instruction CTO — série de 4 PRs de refactor post-audit (spécification, pas de code)

Suite exécutable des recommandations de `docs/audit-cto-2026-07.md` (§7).
**Règles communes** : une PR = un sujet ; suite complète + ruff verts à chaque
PR ; les goldens de parité publication (`test_publication_golden_parity`) sont
un garde-fou absolu — s'ils bougent, la PR est fausse ; aucun changement de
comportement sauf ceux explicitement listés en PR3 (et documentés).

---

## PR1 — Casser les 3 cycles de couche (Élevé, mécanique)

**Principe directeur** : les types/données partagés vivent dans `domain/` (ou
la couche la plus basse qui les connaît). Une couche basse n'importe JAMAIS une
couche haute, même paresseusement. Les 3 cycles actuels sont masqués par des
imports intra-fonction « pour éviter le cycle » — ces commentaires doivent
disparaître avec les cycles.

### 1a. `audit ↔ reporting` — la palette de sévérité

- Site : `audit_bim/audit/findings.py:39` importe (paresseusement)
  `SEVERITY_COLORS` depuis `reporting/theming.py`, alors que `reporting/`
  importe `audit/` partout au niveau module.
- **Faire** : déplacer le mapping sévérité→hex (`SEVERITY_COLORS`) dans
  `audit/findings.py`, à côté de l'enum `Severity` qu'il décrit (c'est une
  convention métier feux-tricolores, pas de la charte de marque — le
  commentaire de `theming.py:79-81` le dit lui-même). `severity_color()`
  devient un lookup direct, sans import.
- `reporting/theming.py` **ré-exporte** `SEVERITY_COLORS` depuis `audit`
  (import descendant, légal) pour que `word_report.py`, `xlsx_annex.py`,
  `avp_i3f.py` restent inchangés.
- Interdit : déplacer les tokens de charte BIMData (`BIMDATA_*`) — eux sont
  bien de la présentation, ils restent dans `theming.py`.

### 1b. `audit ↔ requirements` — la taxonomie IFC

- Sites : `requirements/data_spec_parser.py:33` et
  `data_spec_parser_2026.py:38` importent `..audit.ifc_hierarchy`
  (`normalize_catalog_class`) ; `audit/engine.py:34` importe
  `..requirements.models`.
- **Faire** : déplacer le module `audit/ifc_hierarchy.py` **entier** vers
  `domain/` (nom suggéré : `domain/ifc_taxonomy.py` — c'est de la connaissance
  de taxonomie IFC, pas de l'audit). Mettre à jour tous les imports (greper
  `ifc_hierarchy` : audit, requirements, tests). Pas de shim de compat :
  module interne, aucun consommateur externe.

### 1c. `doe ↔ enrichment` — le modèle d'adresse

- Sites : `doe/address.py:22` importe `enrichment.models.ProjectAddress` au
  niveau module ; `enrichment/address.py:105` importe paresseusement
  `doe.address.extract_address_from_doe` (commentaire « éviter le cycle »).
- **Faire** : déplacer `ProjectAddress` (et ses éventuels types satellites)
  vers `domain/`. Après quoi la dépendance restante est unidirectionnelle
  (`enrichment → doe` pour la fonction d'extraction) : la promouvoir en import
  de niveau module et supprimer le commentaire défensif.

### Verrou architectural (obligatoire dans cette PR)

Ajouter un test `tests/unit/test_architecture.py` qui parse les imports (ast)
de chaque module de `audit_bim/` et **échoue** si : `domain` importe quoi que
ce soit d'`audit_bim` ; `audit` importe `reporting` ou `mcp` ; `requirements`
importe `audit` ; `doe` importe `enrichment` (liste blanche explicite,
extensible). C'est ce test qui empêche la re-dérive — sans lui, la PR ne vaut
rien à 6 mois.

**Acceptation** : plus aucun import intra-fonction motivé par un cycle ;
verrou architectural vert ; goldens inchangés ; suite + ruff verts.

---

## PR2 — `mcp/app.py` : enregistrement explicite, éclatement de `server.py`, découpage de `full_audit` (Élevé, la plus grosse)

### 2a. Extraire l'instance et l'état

- Aujourd'hui : `server.py:62` crée `mcp = FastMCP(...)` ; `tools_actions.py:58`
  et `tools_query.py:38` (et `aliases.py`) font `from .server import mcp` ;
  `server.py:1819-1855` importe `tools_actions`/`tools_query` **en fin de
  fichier** (`noqa: E402, F401`) pour déclencher l'enregistrement par effet de
  bord et ré-exporter les noms. L'ordre d'import est porteur et invisible.
- **Faire** : créer `mcp/app.py` contenant : l'instance `FastMCP`,
  l'enregistrement du middleware (`server.py:66-67` actuel), et le conteneur
  d'état de session (`_State`). AUCUN tool dans `app.py`.
- Tous les modules de tools (`server.py` restant, `tools_actions`,
  `tools_query`, `aliases`) importent `from .app import mcp` (et `_State`).
- L'enregistrement devient **explicite** : une fonction `register_all()` dans
  `mcp/__init__.py` (ou `app.py`) qui importe les modules de tools dans un
  ordre déclaré ; appelée par `__main__.py` et par la fixture de tests. Le bloc
  de fin de fichier et ses `noqa` disparaissent.
- Compat : si des tests/clients référencent `server.prepare_bcf_topics` (ré-
  exports actuels), les conserver une version avec commentaire de dépréciation,
  puis retirer.

### 2b. Éclater les 20 tools restants de `server.py` (1878 l.)

Découpage par domaine, en suivant le modèle existant (`tools_actions`/`tools_query`) :

| Nouveau module | Contenu (depuis `server.py`) |
|---|---|
| `mcp/tools_session.py` | cible/contexte : `set_active_model`, `verify_active_model`, `parse_owner_requirements`, configuration de session |
| `mcp/tools_audit.py` | `full_audit`, `import_preliminary_findings`, consultation de findings de session |
| `mcp/tools_reporting.py` | `generate_word_report`, `generate_xlsx_annex`, `generate_avp_i3f_pack` |
| `mcp/phase.py` (helpers, pas de tools) | `_map_phase`, `_detect_snapshot_phase`, `_phase_question*` (`server.py:982-1072`), `_validate_audit_context` (`:1121`) |

`server.py` disparaît ou ne garde que la compat de ré-export une version.

### 2c. Découper `full_audit` (`server.py:1450`, 356 lignes)

Une fonction par étape nommée, signatures pures autant que possible, le tool
devenant un orchestrateur court (~40 l.) :

1. résolution de cible + contrôle d'identité ;
2. obtention du catalogue (réutiliser `_State.catalog` si sources inchangées —
   deviendra gratuit avec la mémoïsation de PR4) ;
3. extraction du snapshot (cache disque existant) ;
4. `run_audit` ;
5. enrichissement optionnel ;
6. persistance session/sorties ;
7. construction du payload de réponse.

**Contrainte dure** : la signature du tool et la **forme exacte du payload de
réponse** ne changent pas (clients + tests).

**Acceptation** : inventaire de tools identique (49, mêmes noms —
`test_mcp_inventory` doit passer sans modification de liste) ; `python -m
audit_bim.mcp` inchangé ; aucun `noqa: E402` restant dans `mcp/` ; démarrage
stdio pas plus lent (re-mesurer l'import) ; chaque étape de `full_audit`
testée unitairement au moins une fois ; suite + ruff verts.

---

## PR3 — Durcissement transport (Moyen — seule PR avec changements de comportement, tous listés ici)

### 3a. Transport inconnu = fail-closed

- Aujourd'hui : `security.py:58` — `_RUNTIME_TRANSPORT = None` est traité
  comme stdio ⇒ un montage ASGI custom (ou `fastmcp run`) obtient les défauts
  locaux : écritures autorisées (`:110-114`), token-en-paramètre accepté
  (`:147-150`). Seul `__main__.py:62` déclare le transport.
- **Faire** : inverser le défaut — `None` est traité comme **réseau**
  (écritures refusées, token-param refusé, contraintes réseau actives). Les
  entrypoints locaux légitimes se **déclarent explicitement** :
  - `__main__.py` : déjà fait (stdio/http selon args) ;
  - `cli.py` : déclare un mode local au démarrage ;
  - les runners (`scripts/avp_acceptance`, `scripts/a1_replay`,
    `scripts/engine_parity`) : déclarent un mode local (« script ») en tête de
    `main` ;
  - tests : fixture de session qui déclare le mode local (sauf les tests de
    transport qui testent précisément le défaut).
- Précédence inchangée : `AUDIT_BIM_ALLOW_WRITES` explicite gagne toujours.
- Ne PAS choisir la détection runtime par headers HTTP (indéterministe) ; la
  déclaration explicite + défaut fermé est la voie retenue.

### 3b. `AUDIT_INPUT_DIR` obligatoire en réseau

- Aujourd'hui : le fail-fast de `assert_startup_config` (`security.py:236-251`)
  n'exige le confinement d'entrée que si clé service ou prod ; un HTTP dev sans
  clé lit n'importe quel fichier local aux extensions près.
- **Faire** : pour **tout transport réseau**, `AUDIT_INPUT_DIR` absent ⇒ refus
  au démarrage, avec message actionnable. L'échappatoire existante
  `AUDIT_BIM_ALLOW_UNBOUNDED_INPUTS=true` reste le seul contournement (warning
  loggé). Comportement stdio/script : inchangé.

### 3c. Migrer `apply_classifications_from_xlsx` vers prepare→apply

- Aujourd'hui : `server.py:1373-1405` — seul tool d'écriture hors pattern :
  pas de `confirm`, pas de plan scellé, pas de `validate_target` ; gate =
  `dry_run=True` par défaut + `ensure_writes_allowed`.
- **Faire** : reconstruire sur l'infrastructure existante de
  `classification_planner` : lecture du xlsx (sandbox `safe_input_path`,
  inchangé) → **plan scellé** → refus sans `confirm=True`
  (payload `refused_without_confirm` standard) → `validate_target` → apply →
  journal. Le paramètre `dry_run` disparaît au profit du contrat commun
  (l'appel sans `confirm` EST le dry-run : il renvoie le résumé du plan).
- Documenter la rupture dans `docs/mcp_tools.md` (déplacer la ligne de la
  section « Autres écritures (à migrer) » vers la table prepare→apply) et le
  CHANGELOG. Si le nom du tool change, passer par `mcp/deprecation.py` —
  c'est exactement l'usage pour lequel on l'a conservé.

### 3d. Documentation de sécurité (rattrapage F4)

`.env.example` : ajouter, commentées, les variables de sécurité
(`AUDIT_BIM_ALLOW_WRITES`, `AUDIT_BIM_API_KEY`, `AUDIT_BIM_REQUIRE_API_KEY`,
`AUDIT_INPUT_DIR`, `AUDIT_MAX_INPUT_MB`, `AUDIT_BIM_ENV`,
`AUDIT_BIM_ALLOW_ACCESS_TOKEN_PARAM`, `AUDIT_BIM_ALLOW_UNBOUNDED_INPUTS`,
`AUDIT_BIM_SESSION_TTL_S`). Mettre à jour SECURITY.md (nouveau défaut
fail-closed, tableau transport → posture).

**Tests exigés** : transport `None` ⇒ écritures refusées + token-param refusé ;
mode script déclaré ⇒ autorisées ; HTTP sans `AUDIT_INPUT_DIR` ⇒ refus
démarrage ; xlsx-apply sans `confirm` ⇒ `refused: true` ; xlsx-apply complet ⇒
entrée journal. **Vérif transverse** : rejouer le dry-run A1 réel après merge
(les runners déclarent le mode script — c'est le test de non-régression du
jalon précédent).

**Acceptation** : les 3 changements de comportement ci-dessus sont les SEULS ;
chacun testé + documenté ; suite + ruff verts.

---

## PR4 — Factorisation (Moyen, dernier — bénéficie des PRs 1-3)

### 4a. Gardes de scripts → module produit

- Dupliqués : `_assert_outside_repo` ×4 (`avp_acceptance/run_acceptance.py:58`,
  `a1_replay/run_replay.py:43`, `engine_parity/replay.py:22`,
  `engine_parity/extract_artifacts.py:25`) + garde catalogue ×2
  (`run_acceptance.py:70` vs inline `run_replay.py` §3).
- **Faire** : créer `audit_bim/security/guards.py` (PAS `scripts/_guards.py` :
  les runners sont chargés par chemin dans les tests — un module sibling
  poserait un problème de `sys.path` ; le package installé n'en pose aucun)
  exposant `assert_outside_repo(path, *, context: str)` et
  `assert_catalog_usable(docs, catalog)`. Les 4 scripts importent et
  suppriment leurs copies ; les messages contextuels passent par `context`.
  Les tests unitaires des gardes migrent vers un seul fichier.

### 4b. Squelette commun des 4 planners

- Dupliqué : `bcf_planner`, `smartview_planner`, `doe_planner`,
  `classification_planner` (actions/) répètent : gate `confirm` → `load_plan`
  (scellé) → `validate_target` → boucle d'items avec collecte d'erreurs →
  journal (`get_journal`) → redaction → `ActionResult`.
- **Faire** : un helper commun `actions/_apply_runtime.py` :
  `run_apply(plan_path, *, kind, confirm, actual_target, executor)` portant
  TOUTE la logique commune. Chaque planner ne garde que : son `prepare_*`
  (construction du payload) et son exécuteur d'item (callable). Les
  spécificités (`on_conflict` du DOE) passent par l'exécuteur.
- **Contrainte dure** : payloads de refus et de résultat **byte-identiques**
  (clés `refused`, `refused_without_confirm`, compteurs `succeeded/failed`) —
  les tests MCP et les goldens y sont accrochés. Enjeu réel : la garde
  confirm/journal ne peut plus être oubliée par un futur 5ᵉ planner.

### 4c. Mémoïsation de `build_catalog`

- Site : `requirements/catalog.py:19` ; appelé par `parse_owner_requirements`
  (`server.py:226`), `full_audit` (`:1658`), `cli.py:102` — le flux courant
  « preview puis audit » paie deux parses complets (PDF + 2 xlsx).
- **Faire** : cache module-level keyé sur les **chemins résolus + (mtime,
  taille)** des 3 sources. Fichier modifié ⇒ re-parse automatique. Pas de TTL,
  pas d'env de désactivation (le keying suffit). Un fichier de sources
  manquant ⇒ pas de cache (comportement d'erreur inchangé).
- Tests : deux appels mêmes sources ⇒ même objet (identité) ; `touch` d'une
  source ⇒ reconstruction ; sources différentes ⇒ objets différents.

### 4d. Helper suggestions partagé

- Dupliqué byte-à-byte : `word_report._suggestions_map` (`:1230` pré-audit) ≡
  `xlsx_annex._build_suggestions_map` (`:423`).
- **Faire** : une seule fonction dans `classifier/` (à côté de
  `suggest_for_findings`, mêmes défauts `min_confidence=0.4, top_n=1`) ;
  les deux modules reporting la consomment.

**Acceptation** : −~150 lignes dupliquées ; goldens et payloads inchangés ;
dry-run A1 rejoué vert (4a touche ses gardes) ; suite + ruff verts.

---

## Ordre et dépendances

`PR1 → PR2 → PR3 → PR4`. PR2 dépend de PR1 (éclater `server.py` est plus sûr
sans cycles) ; PR3 touche `security.py` + runners et doit précéder 4a (qui
déplace les gardes que 3a modifie chez les runners) ; PR4 ramasse le reste.
Chaque PR est mergeable indépendamment ; en cas d'arbitrage de temps, PR3 est
celle qui réduit un risque réel (les autres réduisent la dette).
