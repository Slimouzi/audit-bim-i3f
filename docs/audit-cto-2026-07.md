# Audit technique CTO — juillet 2026 (base v0.8.0)

Audit exhaustif de la base de code (`audit_bim/`, `scripts/`, `tests/`, `docs/`,
dépendances, CI) mené sur 4 dimensions en parallèle — code mort, architecture &
qualité, sécurité, performance & dépendances — chaque finding contre-vérifié
sur l'arbre v0.8.0 avant conclusion (master a évolué pendant l'analyse ; les
findings périmés ont été écartés). Baseline d'entrée : 1100 tests verts, ruff
clean. **Baseline de sortie : 1116 tests verts, ruff clean, démarrage serveur
−33 %.**

## 1. Synthèse

Le dépôt est en **bon état structurel** : graphe de packages connecté et
majoritairement bien orienté (`mcp` au sommet, `domain` en feuille), pattern
`prepare → apply` scellé systématique, sécurité manifestement pensée
(secure-by-transport, sandbox chemins, redaction, journal, pip-audit/CodeQL en
CI), politique données client stricte, tests denses (unit + integration +
goldens tous vivants). **Aucune faille sécurité Critique ou Élevée.** La dette
réelle se concentre sur : 3 cycles de couche gérés par imports paresseux
défensifs, 2 god modules (`server.py` 1878 l., `reporting/` ~5000 l.),
du code mort résiduel (nettoyé par cet audit), et une doc de référence qui
avait dérivé du code (re-synchronisée).

## 2. Problèmes par criticité

### Critique
Aucun.

### Élevé
| # | Problème | État |
|---|---|---|
| E1 | `requirements.txt` en dérive dangereuse (`pypdf>=4.0` vs pin CVE `>=6.9.1` ; `fastmcp>=0.4` vs `>=3.0`) — installable par habitude alors que rien ne le consomme | **Corrigé** : supprimé (pyproject + uv.lock font foi) |
| E2 | `README` et `docs/mcp_tools.md` (« source de vérité » auto-déclarée) faux : « 10 tools » / « 40 tools » vs **49 réels**, 4 tools absents des tables | **Corrigé** : re-synchronisés |
| E3 | matplotlib importé au chargement du serveur (~330 ms) pour 2 helpers de graphes ; openpyxl (~200 ms) idem via 4 chemins d'import | **Corrigé** : imports paresseux aux sites d'usage ; démarrage mesuré 1,97 s → 1,32 s |
| E4 | Cycle de couche `audit ↔ reporting` (`findings.py` importe la palette de `reporting.theming`) | **Recommandé** (refactor) : déplacer le mapping sévérité→couleur vers `audit`/`domain` |
| E5 | God module `mcp/server.py` (1878 l., 20 tools + enregistrement par effet de bord `from .server import mcp` en fin de fichier, ordre d'import load-bearing sous `noqa`) | **Recommandé** : extraire `mcp/app.py` (instance + état), éclater les tools par domaine ; découper `full_audit` (356 l.) |

### Moyen
| # | Problème | État |
|---|---|---|
| M1 | Gardes secure-by-transport inactives si le serveur est monté hors `python -m audit_bim.mcp` (transport `None` = stdio ⇒ écritures autorisées en HTTP embarqué) | **Recommandé** : fail-closed (`None` = réseau) ou détection runtime du transport |
| M2 | `apply_classifications_from_xlsx` hors pattern prepare→apply (pas de `confirm`, pas de scellé, pas de `validate_target` ; gate = `dry_run` + `ensure_writes_allowed`) — déjà tracé dans `mcp_tools.md` § « à migrer » | **Recommandé** : migrer vers prepare/apply |
| M3 | Identifiants client réels versionnés (cloud/project/model I3F dans README, docs de validation, 2 tests ; chemins personnels `/Users/stani/…` dans les exemples) | **Recommandé** : IDs fictifs dans les tests/README ; décision MOA pour les docs de validation (traçabilité vs discrétion) |
| M4 | Lecture fichiers non bornée par défaut sans `AUDIT_INPUT_DIR` en HTTP dev sans clé (whitelist extensions seule limite) | **Recommandé** : exiger `AUDIT_INPUT_DIR` pour tout transport réseau |
| M5 | 3 cycles de couche gérés par imports paresseux (`audit↔reporting`, `audit↔requirements`, `doe↔enrichment`) | **Recommandé** : promouvoir les types partagés (`ProjectAddress`, `ifc_hierarchy`, palette) dans `domain/` |
| M6 | Duplication : `_assert_outside_repo` ×4 scripts, garde catalogue ×2, `_suggestions_map` ≡ `_build_suggestions_map`, squelette commun des 4 planners | **Recommandé** : `scripts/_guards.py` + abstraction `apply_plan` commune (la garde confirm/journal/redaction en un seul point) |
| M7 | `build_catalog` re-parse PDF + 2 xlsx à chaque appel (preview puis full_audit = double parse) | **Recommandé** : mémoïsation par (path, mtime, size) |
| M8 | `deprecation.py` production-mort (registre vidé en v0.5.0, seuls ses tests le consomment) | **Décision CTO : conservé** — infrastructure documentée de dépréciation, réutilisable ; git l'archive si on change d'avis |

### Faible
`ApiKeyMiddleware` vérifié à `initialize` seulement (défense en profondeur : re-vérifier par tool) · scellé SHA-256 non keyé (tamper-evident, pas tamper-proof — HMAC si menace co-processus) · actions GitHub épinglées par tag pas SHA · `charset-normalizer 3.4.8` yanked dans le lock (regen au prochain bump) · `.env.example` n'expose aucune variable de sécurité (documentées dans README/SECURITY) · 37 fonctions ≥ 80 l. (activer `mccabe.max-complexity`) · franglais isolé `ControleMaquettesSource` · Géorisques : 3 GET séquentiels sans `Session` · docs de pilotage datées mélangées aux specs pérennes (proposer `docs/history/`) · `examples/` non lié depuis le README principal.

## 3. Changements appliqués (ce commit)

**Performance (mesuré)**
- matplotlib paresseux (`word_report._plt()`), openpyxl paresseux aux 4 sites
  (`data_spec_parser`, `naming_spec_parser`, `classifier/xlsx_reader`,
  `doe/extractors/excel`) avec `patch_openpyxl()` déplacé aux sites d'usage et
  rendu explicite chez les consommateurs qui en dépendaient par effet de bord
  (`avp_i3f`, `avp_sources`). **Import serveur : 1,97 s → 1,32 s.**
- Matcher DOE : liste des candidats (invariante) sortie de la boucle des
  enregistrements — supprime un rebuild O(records × éléments).

**Code mort supprimé** (zéro référence vérifiée, tests compris, avant chaque
suppression)
- `audit_bim/reporting/korhus_brand.py` (shim de compat, 5 versions sans
  consommateur) ; `_para_or_na`, `_generate_recommendations` (supersédé),
  `_iter_non_empty`, `journal_path_from_env`, dataclass `TabularSource`,
  constantes `COL_DEFINITION`/`COL_PHASES`, 12/18 alias de charte dépréciés de
  `theming.py`, + les 2 imports (`Iterable`, `os`) que seuls ces morts
  utilisaient. Commentaires mensongers associés purgés.

**Sécurité / hygiène**
- `requirements.txt` supprimé (E1) + `MANIFEST.in` ajusté.
- `.gitignore` : `*.key`, `*.pem`, `.env.*` (hors `.env.example`).

**Documentation**
- README : arbre `mcp/` corrigé ; `docs/mcp_tools.md` : 49 tools, ajout des 4
  manquants (`generate_avp_i3f_pack`, `import_preliminary_findings`,
  `prepare_smart_view_from_filter_plan`, `show_filtered_objects_in_viewer`) ;
  `scripts/mcp-stdio.sh` référencé depuis `claude_desktop_local.md` (il était
  orphelin) ; CHANGELOG « Unreleased » documentant le tout.

**Vérification** : suite complète **1116 passed + 5 skipped**, ruff clean,
import serveur re-mesuré ×2.

## 4. Ce qui a été vérifié et jugé SAIN
Aucun secret réel versionné (arbre **et** historique, 95 commits) · aucune
dépendance tierce ou first-party inutilisée (les 11 tierces + 7 first-party ont
toutes un consommateur réel ; openpyxl lit / xlsxwriter écrit — les deux sont
justifiés) · pip-audit : 0 vulnérabilité connue · pas d'`eval`/`exec`/`pickle`/
`yaml.load`/`shell=True` ; unique `subprocess` sain (args liste + timeout) ·
path-traversal : sandbox `safe_*` présente à tous les sites de chemins fournis
par le modèle · SSRF : URL viewer épinglée `platform.bimdata.io` · scellés :
les 4 `apply_*` valident confirm → seal → target → journal, items relus du plan
scellé uniquement · workflows CI : permissions minimales, pas de
`pull_request_target` · goldens tous consommés · aucun TODO/FIXME fossile ·
skips de tests tous légitimes (gardes d'environnement) · `.env.example` : toutes
les variables lues, toute la config consommée · `aliases.py` : 8 tools vivants
documentés (PAS du code mort) · runners `scripts/` tous référencés docs/tests.

## 5. Sandbox (mission §4)
Aucun dossier sandbox/playground/démo mort dans le dépôt. Les seuls « sandbox »
sont (a) le package first-party `bim_sandbox` — **du produit vivant** (confinement
I/O, importé par `safe_paths`) — et (b) l'ex-environnement d'exécution isolé,
**déjà supprimé** par décision gelée (cf. `docs/instruct-prod-and-field-path-freeze.md`
§3.1). La seule sandbox candidate historique (`codex/mcp-setup-web`) a été
archivée/supprimée au nettoyage des branches. Rien d'autre à supprimer.

## 6. Risques résiduels
1. **E4/E5/M5 non appliqués ici** (refactors de structure) : à faire en PRs
   dédiées avec la suite en garde-fou — les appliquer dans le même lot que cet
   audit aurait mélangé nettoyage prouvable et restructuration à risque.
2. **M1/M4** : sûrs dans le déploiement documenté (`python -m audit_bim.mcp`) ;
   le risque n'existe que pour un montage ASGI custom — à corriger avant tout
   déploiement HTTP mutualisé.
3. `korhus_brand.py` et les 12 alias supprimés : risque faible d'intégration
   externe encore dessus — CHANGELOG l'annonce ; restauration triviale via git.
4. Les mesures de perf (#import) sont locales à cette machine ; l'ordre de
   grandeur (−600 ms) est robuste, pas la valeur exacte.

## 7. Plan d'action recommandé (ordre)
1. **PR refactor couches** : palette sévérité → `audit`/`domain` (E4) ;
   `ProjectAddress` + `ifc_hierarchy` → `domain/` (M5). Petite, mécanique.
2. **PR `mcp/app.py`** : casser l'enregistrement par effet de bord, éclater
   `server.py`, découper `full_audit` (E5). La plus grosse ; à faire avant que
   `server.py` ne grossisse encore.
3. **PR durcissement transport** : fail-closed transport inconnu (M1) +
   `AUDIT_INPUT_DIR` obligatoire en réseau (M4) + migration
   `apply_classifications_from_xlsx` vers prepare/apply (M2).
4. **PR factorisation** : `scripts/_guards.py`, `apply_plan` commun, helper
   suggestions partagé (M6) ; mémoïsation `build_catalog` (M7).
5. Au fil de l'eau : IDs fictifs (M3), pins SHA des actions, `mccabe`,
   `docs/history/`, Session Géorisques, lien `examples/` dans le README.
