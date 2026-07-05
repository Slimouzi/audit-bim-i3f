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

**Frontière (arrêtée par le CTO) :**

| Dans `bim-audit-engine` (générique) | Hors package (reste `audit-bim-i3f`) |
|---|---|
| **protocole de règle** (`Rule`) | ingestion CCH : `build_catalog` + parsers (PDF/xlsx) |
| **boucle d'exécution** `run_audit` (liste de règles **injectable**) | le **jeu de règles I3F** (contenu des 6 fonctions `audit_*`) |
| **agrégation** → `AuditResult` | littéraux I3F (`ref_cch`, patterns `XXXXL-YYYY`, « logement/lgt », suffixes d'étage…) |
| **schéma** `RequirementsCatalog` + sous-modèles + `BIMPhase` | couplage `classifier` UniFormat (cohérence niveau 3) |
| helpers génériques : `ifc_hierarchy` (expand_class), `validators`, `normalizer` (accès Pset), adaptateur géométrie `preliminary` | textes français `recommended_action`/`expected` |

**`load_preliminary_findings`** (adaptateur JSON géométrie `ifc-openshell` →
`Finding`) est **générique** (ne lit ni catalogue ni snapshot) → dans le package.

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

Champs : `phase: BIMPhase`, `catalog: RequirementsCatalog`, `snapshot:
ModelSnapshot`, `findings: list[Finding]`. Méthodes : `count_by_theme/severity/
error_type/ifc_type`, `filter(...)`, `conformity_rate()`, `summary()`.
Aucune logique I3F — pur agrégat/statistiques sur des `Finding`.

### 2.2 `run_audit` (`engine.py:176-231`) — **à rendre générique (registre)**

Aujourd'hui : appelle six règles en dur, `extend` une liste, trie stable par
`(severity_rank, theme, error_type, ifc_type, name)`, retourne `AuditResult`.
Cible : `run_audit(snap, catalog, phase, rules: Sequence[Rule]) -> AuditResult`
où `rules` est **injecté**. La façade audit-bim passe son jeu I3F.

### 2.3 Protocole `Rule` — **nouveau, dans le package**

```python
class Rule(Protocol):
    def __call__(self, snap: ModelSnapshot, catalog: RequirementsCatalog,
                 phase: BIMPhase) -> list[Finding]: ...
```
Convention actuelle (module-level `audit_<name>(snap, catalog, phase)`) — à
**normaliser** : `audit_naming` doit accepter `phase` (même inutilisé).

### 2.4 Schéma `RequirementsCatalog` (`requirements/models.py:121`) — **générique**

Conteneur « attendus » : `properties: list[PropertySpec]`, `naming_rules:
list[NamingRule]`, `storey_names`, `zone_specs`, `room_specs` + provenance.
Méthodes de requête : `properties_for(ifc_class, phase)`, `naming_rule_for(...)`.
Sous-modèles : `PropertySpec`, `NamingRule`, `RoomSpec`, `ZoneSpec`,
`StoreyName`, **`BIMPhase`**. → **dans le package**. Fuite I3F mineure :
`PropertySpec.usage_3f` / `ref_cch`, `ZoneSpec.localisation` PP/PC (champs
optionnels neutres — cf. §8).

### 2.5 Helpers génériques → **dans le package**

- `audit/ifc_hierarchy.py` : `expand_class`, `IFC_SUBCLASSES`,
  `normalize_catalog_class` — mécanique de sous-classes IFC.
- `audit/validators.py` : `validate_property_value` (heuristiques
  numériques/booléennes/lat-lon).
- `extraction/normalizer.py` : `get_attribute`, `resolve_value` (accès
  Pset/attribut normalisé) — **à déplacer dans le package** (générique).
- `audit/preliminary.py` : `load_preliminary_findings` (adaptateur géométrie).

### 2.6 Les 6 règles `audit_*` — **restent dans `audit-bim-i3f`** (v0.1.0)

`spatial`, `naming`, `classifications`, `properties`, `uniqueness`, `lists`.
Même quand la **mécanique** est générique (regex, appartenance à liste fermée,
présence), le **contenu** porte des littéraux I3F (`ref_cch="Chap 6.3.2.1"`,
pattern `XXXXL-YYYY`, « logement/lgt », suffixes `TOITURE/ENTRESOL/COMBLES`,
couplage `classifier` UniFormat). **Décision v0.1.0** : le package fournit le
**protocole + la boucle + les helpers** ; les **6 règles restent côté I3F** et
sont **injectées** dans `run_audit`. Une factorisation ultérieure de « règles
génériques par défaut » (mécanique de `properties`/`uniqueness`) est possible en
v0.2 (cf. §8).

### 2.7 Ce qui reste **hors** package (I3F)

- `requirements/catalog.py::build_catalog` + parsers
  (`data_spec_parser*.py`, `naming_spec_parser.py`, `pdf_parser.py`) — ingestion
  CCH.
- Les 6 fonctions de règles + leurs constantes I3F.
- `classifier` (catalogue UniFormat + suggester) — dépendance lourde ; la
  cohérence niveau 3 dans `classifications.py` reste I3F.

## 3. Contrats

- **Entrée `run_audit`** : `ModelSnapshot` (bim-core), `RequirementsCatalog`
  (schéma package), `BIMPhase` (package), `rules: Sequence[Rule]` (injecté).
- **Règle** : `(snap, catalog, phase) -> list[Finding]`.
- **Sortie** : `AuditResult` (agrégats + `summary()`), findings triés
  sévérité-d'abord (ordre **déterministe** figé).
- **Dépendances** : `bim-core` (contrats + snapshot) **uniquement**.

## 4. Frontière — le seul refactor structurant

**Registre/injection de règles.** `engine.py:211-217` (liste hardcodée) devient
un paramètre `rules`. La façade audit-bim conserve `run_audit(snap, catalog,
phase)` **inchangé pour les call-sites** (`cli.py:118`, `server.py:601`,
`server.py:1732`) en l'implémentant comme
`engine.run_audit(snap, catalog, phase, rules=I3F_RULES)` où `I3F_RULES` est la
liste ordonnée des 6 règles I3F. **Zéro changement de call-site.**

**Normalisation `audit_naming`** : ajouter `phase` (inutilisé) pour respecter le
protocole `Rule` uniforme.

**Consommateurs à préserver** (façade, zéro réécriture) : `cli.py`,
`mcp/server.py` (`run_audit`, `AuditResult`), tout ce qui importe
`RequirementsCatalog`/`BIMPhase` depuis `requirements.models`.

## 5. Ordre des PR (à valider)

Aligné sur le schéma éprouvé (bim-core → … → bim-publication) :

1. **PR scope (celle-ci)** — doc figé, aucun code applicatif.
2. **Package pur `bim-audit-engine` + tag `bim-audit-engine-v0.1.0`** : protocole
   `Rule`, `run_audit(rules injectable)`, `AuditResult`, schéma
   `RequirementsCatalog` + sous-modèles + `BIMPhase`, helpers (`ifc_hierarchy`,
   `validators`, `normalizer`, `preliminary`). Dépend de `bim-core`. Tests
   directs (moteur avec règles factices + agrégation + tri déterministe).
3. **PR adoption (infra-only)** dans `audit-bim-i3f` — dépendance (tag Git +
   `[tool.uv.sources]`), preinstall CI/release, README.
4. **PR shims** : `audit_bim.audit.engine` (AuditResult/run_audit),
   `requirements.models` (schéma), `ifc_hierarchy`/`validators`/`normalizer`/
   `preliminary` deviennent des ré-exports/adaptateurs ; `run_audit` façade
   injecte `I3F_RULES` ; `audit_naming` normalisée. Tests d'identité + parité.

Suppression de l'ancien code **seulement après preuve** : parité des `AuditResult`
(mêmes findings, même ordre, mêmes agrégats) sur fixtures + suite moteur
inchangée + audit réel I3F non régressé.

## 6. Non-objectifs

- Pas d'extraction des parsers CCH ni de `build_catalog` (restent I3F).
- Pas d'extraction du contenu des 6 règles (restent I3F, injectées).
- Pas de dépendance `classifier`/réseau/ingestion dans le package.
- **Aucun renommage** d'`audit-bim-i3f` ni du namespace `audit_bim`.
- Pas de factorisation des « règles génériques par défaut » en v0.1.0 (v0.2).

## 7. Critères de parité

- **`run_audit` façade** produit un `AuditResult` **identique** (findings, ordre
  de tri, agrégats `count_by_*`, `conformity_rate`, `summary`) avant/après, sur
  fixtures snapshot+catalogue déterministes.
- **Suite moteur existante inchangée et verte** (`test_audit_engine.py`,
  `test_audit_findings.py`, `test_audit_validators.py`,
  `test_audit_ifc_hierarchy.py`, `test_preliminary_provenance.py`).
- **Tests d'identité de façade** : `audit_bim.audit.engine.run_audit is
  bim_audit_engine.run_audit` (ou adaptateur prouvé équivalent),
  `AuditResult is …`, schéma `RequirementsCatalog is …`.
- **Nouveaux tests package** : `run_audit` avec règles factices (ordre
  d'exécution, agrégation, tri sévérité-d'abord), protocole `Rule`.
- **Garde de pureté** (CI package) : interdiction d'`import audit_bim`, de réseau,
  d'ingestion de document dans le package.

## 8. Décisions figées (CTO)

Les quatre recommandations sont **validées telles quelles** — le package peut
être codé sur ces bases :

1. **Champs I3F du schéma** : **conservés comme champs optionnels neutres** dans
   le package (`PropertySpec.usage_3f`/`ref_cch`, `ZoneSpec.localisation` PP/PC)
   — découplage total, churn minimal.
2. **Périmètre v0.1.0** : moteur **+ helpers** (`ifc_hierarchy`, `validators`,
   `normalizer`, `preliminary`) ; **les 6 règles restent côté I3F** et sont
   **injectées**. « Règles génériques par défaut » différées (v0.2).
3. **`normalizer`** (`extraction/normalizer.py`) : **déplacé dans le package**
   (accès Pset générique, utilisé par toutes les règles).
4. **Protocole `Rule`** `(snap, catalog, phase) -> list[Finding]` **confirmé** ;
   `audit_naming` **normalisée** pour accepter `phase`.

**Suite d'exécution** : package pur + tag `bim-audit-engine-v0.1.0` → adoption
infra → shims (façade `run_audit` injectant `I3F_RULES`, zéro changement de
call-site).
