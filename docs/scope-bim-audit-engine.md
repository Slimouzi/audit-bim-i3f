# Scope — package `bim-audit-engine` (moteur d'audit générique)

Document d'architecture **figé avant tout code**. Il cartographie le **moteur
d'audit** existant d'`audit-bim-i3f` (`audit_bim/audit/*` + les schémas de
`audit_bim/requirements/models.py`), fixe la frontière **moteur générique vs
règles I3F**, les contrats, l'ordre des PR et les critères de parité.

**Cette PR ne modifie aucun code applicatif** — inventaire et décision seulement.

Objectif : extraire un **moteur d'audit réutilisable** (protocole de règle,
boucle d'exécution, agrégation → `AuditResult`) en un package, **en laissant les
règles I3F et l'ingestion CCH dans `audit-bim-i3f`**. La généricité vit dans le
package ; la spécialisation I3F reste dans le MCP. **On ne renomme ni
`audit-bim-i3f` ni le namespace `audit_bim`** (décision CTO).

## 0. Décisions figées (revue CTO)

**Nom : `bim-audit-engine`.** Dépend de **`bim-core` uniquement** (contrats
`Finding`/`Severity`/`Theme`/`ErrorType`, `ModelSnapshot`). Aucune dépendance à
`audit-bim-i3f`, aucun réseau, aucune ingestion de document.

> **Amendement CTO (v0.1 resserré).** La première version du scope
> **surestimait** la généricité. Corrections figées ci-dessous : le **catalogue**
> et la **phase** sont **génériques par paramètres de type** (le package n'impose
> **pas** `RequirementsCatalog`/`BIMPhase`, qui portent des concepts I3F —
> obligatoires/défauts, `localisation` PP/PC). On n'extrait du `normalizer` que
> les **primitives neutres** (`get_attribute`, `get_property`) ; les fallbacks
> **ArchiCAD/CCH** restent I3F. **`preliminary.py` reste I3F en v0.1** (sévérités
> métier, textes français, seuils, provenance MOA — ce n'est pas un simple
> adaptateur).

**Frontière (amendée, figée CTO) :**

| Dans `bim-audit-engine` (v0.1, réellement générique) | Hors package (reste `audit-bim-i3f`) |
|---|---|
| **protocole `Rule`** (générique sur les types catalogue & phase) | schéma `RequirementsCatalog` + sous-modèles + **`BIMPhase`** (concepts I3F) |
| **boucle d'exécution** `run_audit` (règles **injectables**) + **tri déterministe** | ingestion CCH : `build_catalog` + parsers (PDF/xlsx) |
| **agrégation** → `AuditResult` (générique sur catalogue/phase) | le **jeu de règles I3F** (contenu des 6 `audit_*`) + littéraux (`ref_cch`, `XXXXL-YYYY`, « logement », suffixes) |
| helpers **réellement purs** : `ifc_hierarchy` (`expand_class`), `validators`, primitives `get_attribute`/`get_property` | fallbacks **ArchiCAD/CCH** du `normalizer` + couplage `classifier` UniFormat |
| — | **`preliminary.py`** (adaptateur géométrie : sévérités/seuils/textes MOA) — reste I3F en v0.1 |

## 1. Constat — le moteur est déjà faiblement couplé

Tout le code cité existe déjà (`master`). Points clés relevés (carte
d'exploration) :

- `run_audit(snap: ModelSnapshot, catalog: RequirementsCatalog, phase: BIMPhase)
  -> AuditResult` (`audit/engine.py:176`). Il ne **parse rien** : il reçoit un
  catalogue déjà construit. **Faible couplage** : aucun import de `build_catalog`
  ni des parsers CCH.
- Les règles **n'ingèrent aucun document** : elles *interrogent* le catalogue et
  le snapshot. Les éléments circulent en **`dict`** (pas de `BimObject`).
- `Finding`/`Severity`/`Theme`/`ErrorType` sont **déjà dans `bim-core`**
  (`audit/findings.py:12` ré-exporte `bim_core.findings`). `ModelSnapshot` idem.
- **Un seul vrai point de friction** : la liste des règles est **hardcodée**
  dans `run_audit` (`engine.py:211-217`, six appels en dur) — pas de registre ni
  de protocole. Et `audit_naming` omet le paramètre `phase` (signature non
  uniforme).

## 2. Inventaire

### 2.1 `AuditResult` (`audit/engine.py:34-173`) — **générique**

Champs : `phase`, `catalog`, `snapshot: ModelSnapshot`, `findings:
list[Finding]`. Méthodes : `count_by_theme/severity/error_type/ifc_type`,
`filter(...)`, `conformity_rate()`, `summary()`. Aucune logique I3F — pur
agrégat/statistiques sur des `Finding`. **`phase`/`catalog` sont typés
génériquement** (`AuditResult[CatalogT, PhaseT]`) : le package ne référence ni
`RequirementsCatalog` ni `BIMPhase`.

### 2.2 `run_audit` (`engine.py:176-231`) — **règles injectables + génériques**

Aujourd'hui : appelle six règles en dur, `extend` une liste, trie stable par
`(severity_rank, theme, error_type, ifc_type, name)`, retourne `AuditResult`.
Cible : `run_audit(snap: ModelSnapshot, catalog: CatalogT, phase: PhaseT,
rules: Sequence[Rule[CatalogT, PhaseT]]) -> AuditResult[CatalogT, PhaseT]` — le
package ne connaît ni le type concret du catalogue ni celui de la phase. La
façade audit-bim passe son `RequirementsCatalog`/`BIMPhase` **et** son jeu I3F.
Le **tri déterministe** reste dans le package.

### 2.3 Protocole `Rule` — **générique (dans le package)**

```python
CatalogT = TypeVar("CatalogT")
PhaseT = TypeVar("PhaseT")

class Rule(Protocol[CatalogT, PhaseT]):
    def __call__(self, snap: ModelSnapshot, catalog: CatalogT,
                 phase: PhaseT) -> list[Finding]: ...
```
Le package n'impose **pas** `RequirementsCatalog`/`BIMPhase` — ce sont des
paramètres de type. Convention actuelle (`audit_<name>(snap, catalog, phase)`) à
**normaliser** côté I3F : `audit_naming` doit accepter `phase` (même inutilisé).

### 2.4 Schéma `RequirementsCatalog` (`requirements/models.py:121`) — **reste I3F**

Le conteneur d'« attendus » et ses sous-modèles (`PropertySpec`, `NamingRule`,
`RoomSpec`, `ZoneSpec`, `StoreyName`) **+ `BIMPhase`** portent des concepts
**I3F** : champs obligatoires/défauts, `ZoneSpec.localisation` PP/PC
(`models.py:93`), `PropertySpec.usage_3f`/`ref_cch`. → **restent dans
`audit-bim-i3f`** ; le moteur les consomme via paramètres de type (§2.2/§2.3).

### 2.5 Helpers — **seules les primitives neutres** dans le package

- **Dans le package** : `audit/ifc_hierarchy.py` (`expand_class`,
  `IFC_SUBCLASSES` — mécanique de sous-classes IFC), `audit/validators.py`
  (`validate_property_value`), et **uniquement** les primitives neutres d'accès
  Pset/attribut `get_attribute` / `get_property` (extraites de `normalizer`).
- **Restent I3F** : les **fallbacks ArchiCAD/CCH français** et la logique CCH du
  `normalizer` (`extraction/normalizer.py:26`).

### 2.6 Les 6 règles `audit_*` + `preliminary.py` — **restent I3F** (v0.1)

`spatial`, `naming`, `classifications`, `properties`, `uniqueness`, `lists` :
mécanique parfois générique, mais **contenu I3F** (`ref_cch`, `XXXXL-YYYY`,
« logement », suffixes, couplage `classifier` UniFormat) → **restent côté I3F**,
**injectées** dans `run_audit`. **`preliminary.py`** (`load_preliminary_findings`)
porte des **sévérités métier, textes français, seuils et provenance MOA**
(`rules/preliminary.py:36`) — **ce n'est pas un adaptateur neutre** → **reste
I3F en v0.1**. Factorisation de « règles génériques par défaut » et d'un
adaptateur géométrie neutre : différée (v0.2, cf. §8).

### 2.7 Ce qui reste **hors** package (I3F)

- **Schéma `RequirementsCatalog` + sous-modèles + `BIMPhase`** (concepts I3F).
- `requirements/catalog.py::build_catalog` + parsers
  (`data_spec_parser*.py`, `naming_spec_parser.py`, `pdf_parser.py`) — ingestion
  CCH.
- Les 6 fonctions de règles + leurs constantes I3F ; **`preliminary.py`** (v0.1).
- **Fallbacks ArchiCAD/CCH** du `normalizer`.
- `classifier` (catalogue UniFormat + suggester) — dépendance lourde ; la
  cohérence niveau 3 dans `classifications.py` reste I3F.

## 3. Contrats

- **Entrée `run_audit`** : `ModelSnapshot` (bim-core), `catalog: CatalogT`
  (type **générique** — I3F passe `RequirementsCatalog`), `phase: PhaseT`
  (générique — I3F passe `BIMPhase`), `rules: Sequence[Rule[CatalogT, PhaseT]]`
  (injecté).
- **Règle** : `(snap, catalog, phase) -> list[Finding]` (générique).
- **Sortie** : `AuditResult[CatalogT, PhaseT]` (agrégats + `summary()`), findings
  triés sévérité-d'abord (ordre **déterministe** figé).
- **Dépendances** : `bim-core` (contrats + snapshot) **uniquement**.

## 4. Frontière — le seul refactor structurant

**Registre/injection de règles.** `engine.py:211-217` (liste hardcodée) devient
un paramètre `rules`. La façade audit-bim conserve `run_audit(snap, catalog,
phase)` **inchangé pour les call-sites** (`cli.py:118`, `server.py:601`,
`server.py:1732`) en l'implémentant comme
`engine.run_audit(snap, catalog, phase, rules=I3F_RULES)` où `catalog`/`phase`
sont les types I3F (`RequirementsCatalog`/`BIMPhase`) et `I3F_RULES` la liste
ordonnée des 6 règles I3F. **Zéro changement de call-site.**

**Normalisation `audit_naming`** : ajouter `phase` (inutilisé) pour respecter le
protocole `Rule` uniforme.

**Consommateurs à préserver** (façade, zéro réécriture) : `cli.py`,
`mcp/server.py` (`run_audit`, `AuditResult`), les imports de
`RequirementsCatalog`/`BIMPhase` (**inchangés**, restent dans
`requirements.models` côté I3F).

## 5. Ordre des PR (à valider)

Aligné sur le schéma éprouvé (bim-core → … → bim-publication) :

1. **PR scope (celle-ci)** — doc figé, aucun code applicatif.
2. **Package pur `bim-audit-engine` + tag `bim-audit-engine-v0.1.0`** (v0.1
   **resserré**) : protocole **générique** `Rule[CatalogT, PhaseT]`,
   `run_audit(rules injectable, catalogue/phase génériques)`, `AuditResult`
   générique, **tri déterministe**, helpers **réellement purs** (`ifc_hierarchy`,
   `validators`, primitives `get_attribute`/`get_property`). **Ni**
   `RequirementsCatalog`/`BIMPhase`, **ni** `preliminary`, **ni** fallbacks
   ArchiCAD/CCH. Dépend de `bim-core`. Tests directs (moteur avec règles factices,
   catalogue/phase factices, agrégation, tri).
3. **PR adoption (infra-only)** dans `audit-bim-i3f` — dépendance (tag Git +
   `[tool.uv.sources]`), preinstall CI/release, README.
4. **PR shims** : `audit_bim.audit.engine` (AuditResult/run_audit),
   `audit/ifc_hierarchy`, `audit/validators` et les primitives extraites du
   `normalizer` deviennent des ré-exports/adaptateurs ; la façade `run_audit`
   injecte `I3F_RULES` (avec `RequirementsCatalog`/`BIMPhase` **locaux**) ;
   `audit_naming` normalisée. `requirements.models`, `preliminary.py` et les
   fallbacks du `normalizer` **ne bougent pas**. Tests d'identité + parité.

Suppression de l'ancien code **seulement après preuve** : parité des `AuditResult`
(mêmes findings, même ordre, mêmes agrégats) sur fixtures + suite moteur
inchangée + audit réel I3F non régressé.

## 6. Non-objectifs

- Pas d'extraction du **schéma** `RequirementsCatalog`/`BIMPhase` (restent I3F ;
  génériques via paramètres de type).
- Pas d'extraction des parsers CCH ni de `build_catalog` (restent I3F).
- Pas d'extraction du contenu des 6 règles ni de `preliminary.py` (restent I3F).
- Pas d'extraction des **fallbacks ArchiCAD/CCH** du `normalizer` (I3F) ; seules
  les primitives `get_attribute`/`get_property` sont extraites.
- Pas de dépendance `classifier`/réseau/ingestion dans le package.
- **Aucun renommage** d'`audit-bim-i3f` ni du namespace `audit_bim`.
- Pas de factorisation des « règles génériques par défaut » ni d'adaptateur
  géométrie neutre en v0.1 (v0.2).

## 7. Critères de parité

- **`run_audit` façade** produit un `AuditResult` **identique** (findings, ordre
  de tri, agrégats `count_by_*`, `conformity_rate`, `summary`) avant/après, sur
  fixtures snapshot+catalogue déterministes.
- **Suite moteur existante inchangée et verte** (`test_audit_engine.py`,
  `test_audit_findings.py`, `test_audit_validators.py`,
  `test_audit_ifc_hierarchy.py`, `test_preliminary_provenance.py`).
- **Tests d'identité de façade** : `audit_bim.audit.engine.run_audit is
  bim_audit_engine.run_audit`, `AuditResult is …`, `ifc_hierarchy.expand_class
  is …`, `validators.validate_property_value is …`, primitives `get_attribute`/
  `get_property is …`. (`RequirementsCatalog`/`BIMPhase`/`preliminary` **restent
  I3F** — pas de test d'identité pour eux.)
- **Nouveaux tests package** : `run_audit` avec règles factices + **catalogue/
  phase factices** (ordre d'exécution, agrégation, tri sévérité-d'abord),
  protocole `Rule` générique.
- **Garde de pureté** (CI package) : interdiction d'`import audit_bim`, de réseau,
  d'ingestion de document dans le package.

## 8. Décisions figées (CTO — amendées)

L'amendement resserre le v0.1 (le premier scope surestimait la généricité) :

1. **v0.1 minimal** : **uniquement** protocole `Rule`, boucle injectable
   `run_audit`, `AuditResult`, **tri déterministe** et helpers **réellement purs**
   (`ifc_hierarchy`, `validators`).
2. **Catalogue & phase génériques par paramètres de type** (`CatalogT`/`PhaseT`) :
   le package **n'impose pas** `RequirementsCatalog`/`BIMPhase` (concepts I3F —
   obligatoires/défauts, PP/PC).
3. **Normalizer** : extraire **seulement** `get_attribute`, `get_property` et
   primitives neutres ; les **fallbacks CCH/ArchiCAD** restent I3F.
4. **`preliminary.py` reste côté I3F en v0.1** (sévérités métier, textes français,
   seuils, provenance MOA — pas un adaptateur neutre).

**Suite d'exécution** : package pur + tag `bim-audit-engine-v0.1.0` → adoption
infra → shims/parité (façade `run_audit` injectant `RequirementsCatalog`/`BIMPhase`
+ `I3F_RULES`, zéro changement de call-site).
