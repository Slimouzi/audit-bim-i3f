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

> **Amendement CTO n°2 (v0.1 minimal — figé).** Les deux versions précédentes du
> scope **surestimaient** la généricité. v0.1.0 est réduit au **cœur moteur** :
> `Rule` générique, `run_audit` injectable, `AuditResult`, **tri déterministe** —
> et **rien d'autre**. Les helpers (`validators`, `ifc_hierarchy`, `normalizer`)
> **restent I3F** en v0.1 : ils sont en réalité **orientés I3F** —
> `validators.py` porte du **vocabulaire français, des règles CCH et des valeurs
> V/F** (`validators.py:9`) ; `IFC_SUBCLASSES` est une **sélection bornée aux
> besoins I3F**, pas une hiérarchie IFC générique (`ifc_hierarchy.py:18`) ;
> `normalizer` embarque les fallbacks ArchiCAD/CCH. Leur extraction fera l'objet
> d'un **scoping distinct** (futur package **`bim-rule-kit`**). Le **catalogue**
> et la **phase** restent **génériques par paramètres de type** (le package
> n'impose **pas** `RequirementsCatalog`/`BIMPhase`). **`preliminary.py` reste
> I3F**.

**Frontière (v0.1 minimal, figée CTO) :**

| Dans `bim-audit-engine` (v0.1 — cœur moteur seul) | Hors package (reste `audit-bim-i3f`) |
|---|---|
| **protocole `Rule`** (générique **contravariant** sur catalogue & phase) | schéma `RequirementsCatalog` + sous-modèles + **`BIMPhase`** (concepts I3F) |
| **boucle** `run_audit` (règles **injectables**) + **tri déterministe** | ingestion CCH : `build_catalog` + parsers (PDF/xlsx) |
| **agrégation** → `AuditResult` (générique catalogue/phase ; `summary()` tolère une phase non-Enum) | le **jeu de règles I3F** (6 `audit_*`) + littéraux (`ref_cch`, `XXXXL-YYYY`…) |
| — | **helpers I3F** : `validators` (vocab FR/CCH, V/F), `ifc_hierarchy`/`IFC_SUBCLASSES` (sélection I3F), `normalizer` (fallbacks ArchiCAD/CCH) → **futur `bim-rule-kit`** |
| — | **`preliminary.py`** (sévérités/seuils/textes MOA) + couplage `classifier` |

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

**Correctif P1 — `summary()` compatible phase non-Enum.** Aujourd'hui
`summary()` fait `self.phase.value` (`engine.py:157`) : une **phase `str`
factice casserait**. À rendre tolérant : valeur d'Enum si disponible, sinon
valeur brute / `str()` — p.ex. `getattr(self.phase, "value", self.phase)`.
Idem pour tout autre accès `.value` sur la phase dans le package.

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
# Utilisés uniquement en **entrée** → contravariants.
CatalogT = TypeVar("CatalogT", contravariant=True)
PhaseT = TypeVar("PhaseT", contravariant=True)

class Rule(Protocol[CatalogT, PhaseT]):
    def __call__(self, snap: ModelSnapshot, catalog: CatalogT,
                 phase: PhaseT) -> list[Finding]: ...
```
`CatalogT`/`PhaseT` sont **contravariants** (n'apparaissent qu'en paramètres). Le
package n'impose **pas** `RequirementsCatalog`/`BIMPhase`. Convention actuelle
(`audit_<name>(snap, catalog, phase)`) à **normaliser** côté I3F : `audit_naming`
doit accepter `phase` (même inutilisé).

### 2.4 Schéma `RequirementsCatalog` (`requirements/models.py:121`) — **reste I3F**

Le conteneur d'« attendus » et ses sous-modèles (`PropertySpec`, `NamingRule`,
`RoomSpec`, `ZoneSpec`, `StoreyName`) **+ `BIMPhase`** portent des concepts
**I3F** : champs obligatoires/défauts, `ZoneSpec.localisation` PP/PC
(`models.py:93`), `PropertySpec.usage_3f`/`ref_cch`. → **restent dans
`audit-bim-i3f`** ; le moteur les consomme via paramètres de type (§2.2/§2.3).

### 2.5 Helpers — **restent I3F en v0.1** (futur `bim-rule-kit`)

Contrairement aux versions précédentes du scope, les helpers **ne sont pas
extraits** en v0.1 — ils sont en réalité **orientés I3F** :

- `audit/validators.py` : **vocabulaire français, règles CCH et valeurs V/F**
  (`validators.py:9`) — pas un validateur neutre.
- `audit/ifc_hierarchy.py` : `IFC_SUBCLASSES` est une **sélection bornée aux
  besoins I3F** (`ifc_hierarchy.py:18`), pas une hiérarchie IFC générique.
- `extraction/normalizer.py` : fallbacks **ArchiCAD/CCH** (`normalizer.py:26`).

Leur extraction (primitives neutres `get_attribute`/`get_property`, hiérarchie
IFC générique, validateur neutre) nécessite un **scoping distinct** → futur
package **`bim-rule-kit`**. Hors v0.1.

### 2.6 Les 6 règles `audit_*` + `preliminary.py` — **restent I3F** (v0.1)

`spatial`, `naming`, `classifications`, `properties`, `uniqueness`, `lists` :
mécanique parfois générique, mais **contenu I3F** (`ref_cch`, `XXXXL-YYYY`,
« logement », suffixes, couplage `classifier` UniFormat) → **restent côté I3F**,
**injectées** dans `run_audit`. **`preliminary.py`** (`load_preliminary_findings`)
porte des **sévérités métier, textes français, seuils et provenance MOA**
(`rules/preliminary.py:36`) — **ce n'est pas un adaptateur neutre** → **reste
I3F**. Factorisation « règles/helpers génériques » : différée (`bim-rule-kit`).

### 2.7 Ce qui reste **hors** package (I3F)

- **Schéma `RequirementsCatalog` + sous-modèles + `BIMPhase`** (concepts I3F).
- `requirements/catalog.py::build_catalog` + parsers
  (`data_spec_parser*.py`, `naming_spec_parser.py`, `pdf_parser.py`) — ingestion
  CCH.
- Les 6 fonctions de règles + leurs constantes I3F ; **`preliminary.py`**.
- **Helpers** `validators`, `ifc_hierarchy` (`IFC_SUBCLASSES`), `normalizer`
  (fallbacks ArchiCAD/CCH) → **futur `bim-rule-kit`** (scoping distinct).
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
   **minimal**) : **uniquement** protocole générique `Rule[CatalogT, PhaseT]`
   (contravariant), `run_audit(rules injectable, catalogue/phase génériques)`,
   `AuditResult` générique (dont `summary()` tolérant une phase non-Enum), **tri
   déterministe**. **Aucun helper** (`validators`/`ifc_hierarchy`/`normalizer`
   restent I3F), **ni** `RequirementsCatalog`/`BIMPhase`, **ni** `preliminary`.
   Dépend de `bim-core`. Tests directs : phase `str` **et** phase `Enum`,
   catalogue factice, **zéro règle** et **plusieurs règles**, agrégation, tri.
3. **PR adoption (infra-only)** dans `audit-bim-i3f` — dépendance (tag Git +
   `[tool.uv.sources]`), preinstall CI/release, README.
4. **PR façade/parité** : `audit_bim.audit.engine` ré-exporte `AuditResult` du
   package (**identité stricte**) et implémente `run_audit(snap, catalog, phase)`
   comme `engine.run_audit(..., rules=I3F_RULES)` — **preuve d'équivalence**, pas
   d'identité de `run_audit` (la façade injecte `I3F_RULES`). `audit_naming`
   normalisée (+`phase`). `requirements.models`, `preliminary.py`, `validators`,
   `ifc_hierarchy` et le `normalizer` **ne bougent pas**.

Suppression de l'ancien code **seulement après preuve** : parité des `AuditResult`
(mêmes findings, même ordre, mêmes agrégats) sur fixtures + suite moteur
inchangée + audit réel I3F non régressé.

## 6. Non-objectifs

- Pas d'extraction du **schéma** `RequirementsCatalog`/`BIMPhase` (restent I3F ;
  génériques via paramètres de type).
- Pas d'extraction des parsers CCH ni de `build_catalog` (restent I3F).
- Pas d'extraction du contenu des 6 règles ni de `preliminary.py` (restent I3F).
- **Aucun helper** extrait en v0.1 : `validators`, `ifc_hierarchy`, `normalizer`
  (fallbacks ArchiCAD/CCH) **restent I3F** → futur `bim-rule-kit`.
- Pas de dépendance `classifier`/réseau/ingestion dans le package.
- **Aucun renommage** d'`audit-bim-i3f` ni du namespace `audit_bim`.

## 7. Critères de parité

- **Preuve d'équivalence `run_audit`** (pas d'identité — la façade injecte
  `I3F_RULES`) : la façade I3F `run_audit(snap, catalog, phase)`, **sans
  changement de signature**, produit un résultat **identique** à
  `bim_audit_engine.run_audit(snap, catalog, phase, rules=I3F_RULES)` — mêmes
  findings, même ordre de tri, mêmes agrégats (`count_by_*`, `conformity_rate`,
  `summary`), sur fixtures déterministes.
- **Identité stricte uniquement pour `AuditResult`** :
  `audit_bim.audit.engine.AuditResult is bim_audit_engine.AuditResult`.
- **Suite moteur existante inchangée et verte** (`test_audit_engine.py`, …).
- **Tests du package** : `run_audit` exécuté avec **phase `str`**, **phase
  `Enum`**, **catalogue factice**, **zéro règle** et **plusieurs règles** —
  ordre d'exécution, agrégation, tri sévérité-d'abord, `summary()` sur phase
  non-Enum. Protocole `Rule` générique (contravariant).
- **Garde de pureté** (CI package) : interdiction d'`import audit_bim`, de réseau,
  d'ingestion de document dans le package.

## 8. Décisions figées (CTO — amendement n°2)

1. **v0.1 minimal** : **uniquement** protocole `Rule` générique, boucle injectable
   `run_audit`, `AuditResult`, **tri déterministe**. **Aucun helper.**
2. **`validators`, `ifc_hierarchy`, `normalizer` restent I3F** en v0.1 (orientés
   I3F : vocab FR/CCH, `IFC_SUBCLASSES` borné, fallbacks ArchiCAD). Leur
   extraction → **scoping distinct `bim-rule-kit`**.
3. **`summary()` tolérant** : valeur d'Enum si dispo, sinon valeur brute / `str()`
   (`getattr(phase, "value", phase)`) — une phase `str` factice ne casse plus.
4. **Équivalence, pas identité, pour `run_audit`** (façade injecte `I3F_RULES`,
   signature inchangée) ; **identité stricte conservée pour `AuditResult`**.
5. **TypeVar `Rule` contravariants** (catalogue/phase en entrée seulement).
6. **Catalogue & phase génériques** ; `RequirementsCatalog`/`BIMPhase` et
   `preliminary.py` restent I3F.

**Suite d'exécution** : package pur + tag `bim-audit-engine-v0.1.0` → adoption
infra → shims/parité (façade `run_audit` injectant `RequirementsCatalog`/`BIMPhase`
+ `I3F_RULES`, zéro changement de call-site).
