# Scope — package `bim-publication` (builders BCF / Smart Views)

Document d'architecture **figé avant tout code**. Il cartographie la couche
**publication** existante d'`audit-bim-i3f` (builders BCF `audit_bim/bcf/builder.py`,
builders Smart Views `audit_bim/smartview/builder.py`, préparation de `WritePlan`
dans `audit_bim/actions/{bcf_planner,smartview_planner}.py`), fixe la frontière du
futur package commun, les contrats, l'ordre des PR et les critères de parité.

**Cette PR ne modifie aucun code applicatif** — inventaire et décision seulement.

Objectif : extraire les **transformations pures** findings → payloads BCF /
Smart Views + **préparation des `WritePlan`** en un package réutilisable, **sans
réécriture de logique** et **sans changement observable**. C'est la brique
logique juste au-dessus de `bim-query`.

## 0. Décisions figées (revue CTO)

**Frontière (arrêtée par le CTO) :**

| Dans `bim-publication` | Hors package (reste `audit-bim-i3f`) |
|---|---|
| builders BCF (`build_bcf_payloads`) | appels réseau BIMData (`client.create_bcf_full_topic`) |
| builders Smart Views (`build_smartview_payloads`, `build_smartview_payload_from_uuids`) | gating `confirm=True` |
| transformation findings → payloads | authentification / credentials |
| **préparation des `WritePlan`** (`prepare_bcf`, `prepare_smart_views`, `prepare_smart_view_from_filter`) | journal d'écriture (`write_journal`) |
| calcul des risques du plan | état MCP (`_State`), chemins sandbox (`safe_paths`) |

**Dépendances autorisées : `bim-core`, et éventuellement `bim-query`.** Rien
d'autre. **Aucune dépendance à `audit-bim-i3f`.** L'exécution distante reste la
responsabilité de **`bimdata-write`** (via le `apply_*` qui reste côté audit).

**Nom : `bim-publication`** (arrêté). Cohérent avec `bim-core`/`bim-query` : la
couche produit des **payloads/plans** à partir de findings normalisés, sans savoir
comment ils seront poussés.

**`bim-query` en dépendance optionnelle.** Les builders **n'en ont pas besoin**.
Seule la **préparation** (`prepare_*`) l'utilise, pour filtrer les findings via
`finding_matches` (`bim_query.filtering`). Si on inclut `prepare_*` dans le package
(recommandé, cf. §4), `bim-query` devient une dépendance **réelle mais bornée**.

## 1. Constat — couche publication déjà en place

Tout le code cité existe déjà dans `audit-bim-i3f` (`master`).

| Module | Rôle | Réseau / I/O / état |
|---|---|---|
| `audit_bim/bcf/builder.py` | findings → payloads BCF FullTopic (multi-couleur, viewpoints, priorité) | **aucun** (sauf `push_bcf_topics`, legacy — cf. §2.4) |
| `audit_bim/smartview/builder.py` | findings → payloads Smart View (coloring minimal, format `bimdata-smartview`) | **aucun** (sauf `push_smart_views`, legacy) |
| `audit_bim/actions/bcf_planner.py` | `prepare_bcf` (filtre + builder + `WritePlan` + risques) / `apply_bcf` (réseau + journal) | prepare : aucun ; apply : réseau+journal |
| `audit_bim/actions/smartview_planner.py` | `prepare_smart_views` / `prepare_smart_view_from_filter` / `apply_smart_views` | idem |
| `audit_bim/actions/plans.py` | persistance/scellé SHA-256/`validate_target` | **sandbox + I/O** → reste hors package |
| `audit_bim/mcp/tools_actions.py` | tools MCP (`prepare_*`/`apply_*`) : `_State`, `confirm`, `ensure_writes_allowed` | **état + gating** → reste hors package |

Les contrats sont déjà modularisés : `Finding`/`Severity`/`Theme` (bim-core),
`FindingFilter` (bim-core), `WritePlan`/`WritePlanKind`/`ActionResult` (bim-core),
`ModelSnapshot` (bim-core), `finding_matches` (bim-query).

## 2. Inventaire de l'existant

### 2.1 Builders BCF (`bcf/builder.py`)

- `build_bcf_payloads(result, *, prefix, model_id, include_overview) -> list[dict]`
  — groupe les findings par `Theme`, un topic BCF par thème (+ topic « Vue
  d'ensemble » multi-couleur optionnel). Payload : titre, description, priorité
  (dérivée de la sévérité max), labels, viewpoints (`selection` + `coloring`),
  `models`.
- Helpers purs : `_build_bcf_topic`, `_build_overview_bcf_topic`, `_max_severity`,
  `_slug`, `_hex_alpha`, `_theme_description`.
- Couleurs : `THEME_COLORS` (de `reporting.theming`) → **couplage à casser** (§4).

### 2.2 Builders Smart Views (`smartview/builder.py`)

- `build_smartview_payloads(result, *, prefix, model_id, include_overview) -> list[dict]`
  — un Smart View par thème, coloring par sévérité, format minimal
  `bimdata-smartview` (omet volontairement les champs BCF pour rester dans le
  panneau Smart Views).
- `build_smartview_payload_from_uuids(uuids, *, title, color, model_id, element_by_uuid) -> dict`
  — Smart View à partir d'une sélection d'UUIDs explicite.
- Helpers : `_build_full_topic`, `_build_overview_topic`, `_severity_color`,
  `_element_name` (nom Revit via `element_by_uuid`).
- Couleurs : `SEVERITY_COLORS` (de `reporting.theming`) → **couplage à casser**.

### 2.3 Préparation `WritePlan` (`actions/{bcf,smartview}_planner.py`)

- `prepare_bcf(result, *, finding_filter, target, prefix, include_overview) -> WritePlan`
  — filtre les findings (`finding_matches`, bim-query) → appelle le builder →
  assemble `WritePlan(kind=BCF_TOPICS, target, summary, items=payloads, risks)`.
  **Aucun réseau, aucun journal, aucun I/O.**
- `prepare_smart_views(...) -> WritePlan` / `prepare_smart_view_from_filter(uuids, ...) -> WritePlan`
  — même schéma (kind `SMART_VIEWS`).
- Ces trois `prepare_*` sont **purs** (au sens réseau/journal/état/sandbox) → **dans
  le package** (cf. §4).

### 2.4 Ce qui reste **hors** package

- `apply_bcf` / `apply_smart_views` : `client.create_bcf_full_topic` (réseau),
  `redact_secrets`, `get_journal().record()`, `validate_target`. → **audit-bim**.
- `push_bcf_topics` / `push_smart_views` (builder.py) : chemins **legacy** qui
  prennent un `BIMDataClient` et écrivent en direct (sans plan scellé ni journal).
  **Non extraits** — restent côté audit (ou à retirer plus tard). Le package ne
  contient **que** les fonctions pures `build_*`.
- `actions/plans.py` (scellé/persistance/sandbox) et `mcp/tools_actions.py`
  (`_State`, `confirm`, `ensure_writes_allowed`) : hors package.

### 2.5 Tests existants

- `tests/unit/test_actions_planners.py` : `prepare_bcf`/`apply_bcf`,
  `prepare_smart_views`/`apply_smart_views` (filtrage, comptes, journal, mismatch
  cible, échec partiel).
- `tests/unit/test_actions_plans.py` : checksum/scellé/round-trip/altération.
- **Pas de test unitaire dédié aux builders** aujourd'hui (couverts indirectement
  via les planners) → le package **ajoutera** des tests directs des `build_*`
  (payloads BCF/SmartView, overview, `from_uuids`, cas vides / UUID manquants).

## 3. Contrats (entrées / sorties figées)

- **Entrée** : une liste de `Finding` (bim-core) + un `phase: str` + un
  `model_id` optionnel + un `prefix`. Pour Smart Views, un `element_by_uuid: dict`
  optionnel (noms Revit). Pour `prepare_*` : `target: dict`
  (`{cloud_id, project_id, model_id}`, données brutes) + `finding_filter:
  FindingFilter | None` (bim-core).
- **Sortie builders** : `list[dict]` (payloads BCF standard / `bimdata-smartview`)
  — schéma exact figé (titre, viewpoints, `coloring`, `components`, `models`,
  priorité/labels pour BCF).
- **Sortie `prepare_*`** : `WritePlan` (bim-core) — `kind`, `target`, `summary`,
  `items=payloads`, `risks`. **Non scellé, non persisté** (le scellé/`save_plan`
  reste côté audit).
- **Palette couleurs** : `THEME_COLORS` (par thème) / `SEVERITY_COLORS` (par
  sévérité) — voir décision §4/§8.

Le vocabulaire (schéma des payloads, couleurs, priorités, format Smart View) est
**le contrat**. Toute évolution se fait des deux côtés.

## 4. Frontière du package `bim-publication` — 2 couplages à casser

**Couplage A — `AuditResult` (type audit-bim).** Les builders lisent aujourd'hui
`result.findings` et `result.phase.value` ; `prepare_*` prend un `AuditResult`.
Comme **aucune dépendance à `audit-bim-i3f`** n'est autorisée, les fonctions du
package prennent des **primitives bim-core** :

- `build_bcf_payloads(findings: list[Finding], *, phase: str, prefix, model_id, include_overview) -> list[dict]`
- `build_smartview_payloads(findings: list[Finding], *, phase, prefix, model_id, include_overview, element_by_uuid=None) -> list[dict]`
- `prepare_bcf(findings: list[Finding], *, phase, finding_filter, target, prefix, include_overview) -> WritePlan`

La façade `audit-bim` conserve les signatures historiques prenant `AuditResult`
en **adaptant** : `build_bcf_payloads(result)` → `pub.build_bcf_payloads(result.findings, phase=result.phase.value, …)`.
Ainsi les call-sites (planners → tools) restent inchangés, comportement identique.

**Couplage B — `reporting.theming`.** `THEME_COLORS`/`SEVERITY_COLORS` viennent de
`audit_bim.reporting.theming`, **aussi importé par `audit/findings.py` et le
reporting Word/xlsx**. On ne peut pas déplacer tout `theming` dans le package
(cela créerait `audit → bim-publication` à rebours). **Recommandation** : le
package **embarque ses propres constantes de publication** `THEME_COLORS` /
`SEVERITY_COLORS` (valeurs **copiées verbatim** pour parité stricte), source de
vérité des couleurs **de publication**. Le reporting garde sa palette. Une
unification ultérieure de la palette dans `bim-core` reste possible (hors scope).
→ **Décision CTO attendue** (§8).

**Consommateurs internes à préserver** (façade, zéro réécriture) :
`actions/bcf_planner.py`, `actions/smartview_planner.py` (si `prepare_*` extrait,
ils ré-exportent depuis le package ; `apply_*` reste local), et indirectement
`mcp/tools_actions.py`.

## 5. Ordre des PR (à valider)

Aligné sur le schéma éprouvé bim-core / bimdata-read / bim-sandbox / bim-query,
+ un replay A1 en clôture :

1. **PR scope (celle-ci)** — doc figé, aucun code applicatif.
2. **Package pur `bim-publication` + tag `bim-publication-v0.1.0`** — builders
   BCF/SmartView + `prepare_*` + palette de publication embarquée + tests directs.
   Dépend de `bim-core` (+ `bim-query` pour le filtrage des `prepare_*`). Zéro
   `audit_bim.*`, zéro réseau, zéro journal, zéro sandbox.
3. **PR adoption (infra-only)** dans `audit-bim-i3f` — dépendance (tag Git +
   `[tool.uv.sources]`), preinstall CI/release, README. Aucun changement de
   comportement.
4. **PR shims** — `bcf/builder.py`, `smartview/builder.py` et les `prepare_*` des
   planners deviennent des ré-exports/adaptateurs fins du package ; `apply_*`
   inchangés. Tests d'identité + parité des payloads.
5. **Replay A1 sandbox** — rejouer la validation write BCF/Smart Views réelle
   (projet bac-à-sable) **après** les shims, pour prouver qu'un plan préparé par
   le package produit des topics/Smart Views valides via `apply_*` + `bimdata-write`.

Suppression de l'ancien code **seulement après preuve** : parité des payloads
(octet à octet sur fixtures) + suite planners inchangée + replay A1 vert.

## 6. Non-objectifs

- Aucune écriture BIMData, aucun appel réseau (reste `apply_*` + `bimdata-write`).
- Aucun gating `confirm`, aucune auth, aucun journal, aucun état MCP.
- Aucune persistance/scellé de plan ni chemin sandbox (`actions/plans.py` reste).
- Pas d'extraction des planners `classification`/`doe` (autres chantiers Write-actions).
- Pas d'extraction des chemins legacy `push_bcf_topics`/`push_smart_views`.
- Pas d'unification de la palette `theming` dans bim-core (décision différée).

## 7. Critères de parité

- **Parité des payloads** : sur fixtures de findings déterministes, les `list[dict]`
  produits par le package sont **identiques** (mêmes clés, couleurs, viewpoints,
  priorités, ordre) à ceux de l'implémentation actuelle.
- **Tests planners existants inchangés et verts** (`test_actions_planners.py`,
  `test_actions_plans.py`) côté façade.
- **Nouveaux tests directs des builders** dans le package (BCF, SmartView,
  overview, `from_uuids`, cas vides / UUID manquants, mapping sévérité→couleur).
- **Tests d'identité de façade** : `audit_bim.bcf.builder.build_bcf_payloads`
  adapte `pub.build_bcf_payloads` (mêmes payloads en sortie).
- **Garde de pureté** (CI package) : interdiction d'`import audit_bim`, de tout
  appel réseau/`client`, de `write_journal`, de `safe_paths` dans le package.
- **Replay A1** : `succeeded>0 / failed=0`, topics + Smart Views visibles dans le
  viewer sandbox.

## 8. Décisions en attente (CTO)

1. **Palette `theming`** : (a) package embarque ses `THEME_COLORS`/`SEVERITY_COLORS`
   verbatim (**recommandé**, découplage total, unification bim-core différée) ;
   ou (b) extraire d'abord la palette partagée dans `bim-core` (chantier préalable).
2. **Périmètre du package** : builders **+** `prepare_*` (**recommandé** — le CTO a
   listé « préparation des `WritePlan` » dans le package ; `bim-query` devient dép.
   réelle bornée) ; ou builders **seuls** (`prepare_*` restent côté audit,
   `bim-query` non requis).
3. **Signature** : confirmer le passage de `AuditResult` → `list[Finding] + phase`
   dans le package, avec adaptation dans la façade audit-bim.
