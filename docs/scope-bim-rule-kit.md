# Scope (étude) — `bim-rule-kit` : validators, hiérarchie IFC, accesseurs

> **Nature de ce document.** Ceci est une **étude de cadrage**, pas un plan de
> migration. Objectif fixé par le CTO : *« étudier séparément validators,
> hiérarchie IFC et accesseurs, **sans les déplacer automatiquement** »*. Aucun
> code n'est extrait sur la base de ce document : il classe chaque symbole
> (générique vs I3F), mesure le couplage réel, et pose les **décisions ouvertes**
> à trancher **avant** toute PR de package.

## 0. Contexte

Lors de l'extraction du moteur (`bim-audit-engine`, v0.1), les helpers d'audit
ont été **explicitement laissés côté I3F** et renvoyés à un futur `bim-rule-kit`
(cf. `scope-bim-audit-engine.md` §2.5). Ce document instruit ce « futur ».

Trois familles, toutes dans `audit-bim-i3f` aujourd'hui :

| Famille | Fichier | Lignes |
|---|---|---|
| Validation de valeurs | `audit_bim/audit/validators.py` | 178 |
| Hiérarchie / classes IFC | `audit_bim/audit/ifc_hierarchy.py` | 91 |
| Accesseurs d'éléments | `audit_bim/extraction/normalizer.py` | 219 |

## 1. Constat de couplage

**Couplage technique : NUL.** Les trois fichiers n'importent que la **stdlib**
(`re`, `typing.Any`) — zéro `audit_bim`, zéro `bim_core`, zéro `requests`, zéro
réseau. Fonctions pures sur `dict`/`str`. Techniquement, tout est extractible
sans effort.

**Couplage sémantique : ÉLEVÉ et MIXTE.** C'est là que se joue la décision. Chaque
fichier **mélange** dans le même module :

- des **primitives génériques** (validation numérique/booléenne, expansion de
  sous-classes IFC standard, accès `Pset.Property` neutre) ;
- des **règles métier I3F / ArchiCAD / CCH** (vocabulaire français, conventions
  « V/F », repli `LongName→Name` ArchiCAD, suffixes I3F `IfcCovering_CEILING`,
  parsing des annexes « à défaut… », « Relatif à la classe… »).

Le vrai travail n'est donc **pas** de « bouger des fichiers » mais de **trancher
la ligne générique/I3F à l'intérieur de chaque fichier**.

**Consommateurs** (11 modules) : les 6 règles `audit/rules/*`, `doe/conflicts.py`,
`doe/matcher.py`, `extraction/__init__.py`, et — important — les parsers de
catalogue `requirements/data_spec_parser.py` + `data_spec_parser_2026.py`
(via `normalize_catalog_class`, ingestion I3F).

## 2. Inventaire par symbole

Légende : **G** = candidat générique (bim-rule-kit envisageable) · **I3F** = métier,
doit rester · **MIX** = corps générique piloté par des données I3F.

### 2.1 `validators.py`

| Symbole | Classe | Note |
|---|---|---|
| `validate_property_value(...)` | **MIX** | Logique de validation générique (numérique ≥ 0, booléen, chaîne, lat/long) **mais** pilotée par des listes de mots-clés **I3F/français** (`_NUMERIC_POSITIVE_KEYS` avec « épaisseur »/« débit », `_BOOL_KEYS` « porteur »/« habitable », `_ALPHANUM_REQUIRED_KEYS`). Le squelette est réutilisable ; la valeur métier est **dans les listes**. |
| `_is_bool_value`, `_expects_bool`, `_has_key` | **MIX** | `_BOOL_STR_VALUES` inclut « V/F/OUI/NON/VRAI/FAUX » (convention CCH française). |

Verdict famille : **difficilement séparable proprement**. Un « validateur
générique » sans les listes ne vaut presque rien ; les listes **sont** l'I3F.

### 2.2 `ifc_hierarchy.py`

| Symbole | Classe | Note |
|---|---|---|
| `IFC_SUBCLASSES` + `expand_class(cls)` | **G** | Connaissance du **schéma IFC standard** (IfcWall → IfcWallStandardCase…). Pur, borné, réutilisable par tout auditeur IFC. Seule vraie primitive « générique nette » du lot. |
| `normalize_catalog_class(raw)` | **I3F** | Parse les étiquettes de l'**annexe Spécifications I3F** : `« à défaut IfcBuildingElementProxy »`, suffixe I3F `IfcCovering_CEILING`, casse `ifcSlab`. Ingestion catalogue → **reste I3F**. |

Verdict famille : **ligne nette**. `expand_class`/`IFC_SUBCLASSES` = générique ;
`normalize_catalog_class` = I3F. C'est le meilleur candidat d'un éventuel kit.

### 2.3 `normalizer.py`

| Symbole | Classe | Note |
|---|---|---|
| `get_attribute(el, name)` | **G** | Accès attribut IFC natif sur le dict élément dénormalisé BIMData (name/longname/objecttype/…, Pset `Attributes`). Neutre. |
| `get_property(el, pset, prop)` | **G** | Accès `Pset.Property` (sous-chaîne tolérée). Neutre. |
| `has_classification`, `classification_codes` | **G** | Lecture des classifications de l'élément. Neutre. |
| `get_attribute_with_fallback` + `ATTRIBUTE_FALLBACKS` | **I3F** | Repli `LongName→Name` = quirk **ArchiCAD** signalé par le CCH. |
| `get_quantity_with_fallback` + `QUANTITY_FALLBACKS` | **I3F** | `AC_Pset_Marque_de_zone`, « Surface/Superficie … mesurée » = **ArchiCAD FR**. |
| `resolve_value(...)` | **I3F** | Interprète les expressions composites des annexes I3F (`« Relatif à la classe IfcName »`, `/`, `.`, repli natif). |
| `NATIVE_IFC_ATTRIBUTES` | **G** | Ensemble d'attributs IFC natifs (constante réutilisable). |

Verdict famille : **ligne nette** mais avec une **dépendance de contrat** (cf. §3) :
les accesseurs « génériques » supposent la **forme du dict élément BIMData**
(`property_sets[].properties[].definition.name/value`, `classifications[].notation`).

## 3. Question structurante — le contrat « élément »

Les accesseurs dits « génériques » (`get_attribute`/`get_property`/…) ne sont
génériques **que vis-à-vis de la forme dénormalisée BIMData** de l'élément. Cette
forme est déjà un **contrat** (produit par `bimdata-read`, modélisé partiellement
par `bim_core.BimObject`). Deux implications :

1. Un `bim-rule-kit` d'accesseurs dépendrait de **où vit ce contrat** — dict brut
   BIMData ? `bim_core.BimObject` ? Le choix conditionne la dépendance du kit.
2. Il y a **recouvrement possible** avec `bim-core` (accès élément) et
   `bim-query` (filtrage/lecture). Un kit d'accesseurs pourrait **doublonner** ou,
   au contraire, **remonter dans bim-core** plutôt que créer un 8ᵉ package.

→ **À trancher avant tout code** (décision D2 ci-dessous).

## 4. Options (aucune n'est retenue par défaut)

- **Option A — statu quo.** Laisser les 3 fichiers dans `audit-bim-i3f`. Coût nul,
  aucune régression possible. Les helpers ne sont partagés par aucun autre repo
  aujourd'hui (contrairement à `bim-sandbox` qui, lui, avait 2 consommateurs).
- **Option B — kit minimal « IFC pur ».** N'extraire **que** le générique net et
  sans dépendance de contrat lourd : `expand_class`/`IFC_SUBCLASSES`,
  `NATIVE_IFC_ATTRIBUTES`. Laisser validators (MIX) et les accesseurs (dépendance
  contrat) côté I3F. Petit package, frontière claire, faible valeur immédiate.
- **Option C — kit « accès élément » via bim-core.** Remonter les accesseurs
  neutres (`get_attribute`/`get_property`/`has_classification`) **dans `bim-core`**
  (à côté de `BimObject`/`ModelSnapshot`) plutôt que dans un nouveau package, et
  laisser tous les replis I3F/ArchiCAD dans `audit-bim`. Évite un 8ᵉ package.
- **Option D — kit large.** Extraire les trois familles avec paramétrage des
  listes I3F (injection de vocabulaire, comme les règles injectables du moteur).
  Le plus ambitieux ; le plus risqué pour la parité ; justifié **seulement** si un
  2ᵉ consommateur réel apparaît (autre CCH, autre bailleur).

## 5. Recommandation (à valider)

Le déclencheur historique d'une extraction dans ce chantier a toujours été un
**besoin de partage réel** (bim-core: contrats communs ; bim-sandbox: 2 MCPs ;
bim-publication/query: frontière métier nette). **Aucun second consommateur
n'existe** pour ces helpers aujourd'hui.

Recommandation : **ne pas créer `bim-rule-kit` maintenant** (Option A par défaut),
et — si l'on veut un premier pas à valeur sûre et sans risque de contrat —
préparer **Option C** (accesseurs neutres → `bim-core`) comme candidat privilégié,
car il supprime une duplication latente au lieu d'ajouter une surface. Décision au
CTO.

## 6. Décisions ouvertes (CTO)

- **D1 — Y a-t-il un besoin de partage réel** (2ᵉ consommateur : autre CCH /
  bailleur / MCP) qui justifie un package ? Sinon → Option A.
- **D2 — Contrat « élément »** : les accesseurs neutres doivent-ils dépendre du
  dict BIMData brut, de `bim_core.BimObject`, ou **remonter dans `bim-core`**
  (Option C) plutôt que dans un nouveau package ?
- **D3 — Périmètre** si extraction : B (IFC pur), C (accès → bim-core), ou D
  (large avec vocabulaire injectable) ?
- **D4 — `normalize_catalog_class`** reste **I3F** (ingestion catalogue) : confirmé ?
- **D5 — validators (MIX)** : accepte-t-on qu'il **reste I3F** tant que le
  vocabulaire n'est pas paramétrable, faute de séparation propre ?

## 7. Non-objectifs (cadre de sécurité)

- **Aucun déplacement automatique** de fichier sur la base de ce document.
- **Aucun** changement de comportement, **aucun** renommage `audit-bim-i3f` /
  `audit_bim`.
- Pas de package créé tant que D1–D3 ne sont pas tranchées.
- Si extraction un jour : même playbook que les 7 précédents (package pur + tag →
  adoption infra → façade/parité) et **parité prouvée** (unit + replay réel),
  jamais de suppression avant preuve.
