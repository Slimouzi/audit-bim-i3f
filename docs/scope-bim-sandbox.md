# Scope — package `bim-sandbox`

Document d'architecture **figé avant tout code**. Il cartographie la sandbox de
chemins (validation inputs/outputs) **dupliquée** entre `audit-bim-i3f` et
`ifc-geometry`, fixe la frontière du package commun `bim-sandbox`, l'ordre des
PR et les critères de parité.

**Cette PR ne modifie aucun code applicatif** — inventaire et décision seulement.

Objectif : une **seule** implémentation de la sandbox de chemins, partagée par
tous les MCP, avec un comportement et des erreurs homogènes.

## 0. Décisions figées (revue CTO)

**Décision 1 — package séparé `bim-sandbox`** (pas un sous-module de `bim-core`).
Raison : `bim-core` reste le noyau de **contrats métier purs** (Finding, BimObject,
filtres, WritePlan, ModelSnapshot) ; `bim-sandbox` porte de l'**infrastructure
runtime** (filesystem, variables d'env, racines I/O, overwrite, exceptions). Les
responsabilités restent lisibles pour les futurs MCP spécialisés.

**Décision 2 — parité stricte des erreurs `overwrite` (pas d'unification en
v0.1.0).** On préserve le comportement historique **par fonction** :
- `safe_export_path(..., overwrite=False)` + fichier existant → `UnsafePathError`
- `safe_output_path(..., overwrite=False)` + fichier existant → `FileExistsError`

Toute harmonisation ira en **v0.2** avec migration explicite.

## 1. Constat — duplication réelle

| | `audit-bim-i3f/audit_bim/safe_paths.py` | `ifc-geometry/ifc_openshell_mcp/safe_paths.py` |
|---|---|---|
| Taille | 273 lignes (riche) | 76 lignes (minimale) |
| Confinement `..` + racine | ✅ | ✅ |
| Env | `AUDIT_INPUT_DIR`, `AUDIT_OUTPUT_DIR`, `AUDIT_MAX_INPUT_MB` | `AUDIT_INPUT_DIR`, `AUDIT_OUTPUT_DIR` |
| Inputs | `safe_input_path` (+ whitelist extensions, taille max, fichier régulier) | `safe_input_path` (whitelist extensions) |
| Outputs | `safe_export_path`, `safe_export_read_path`, `safe_export_dir`, `get_export_root` | `safe_output_path(name)` |
| Erreur | `UnsafePathError(ValueError)` | `ValueError` / `FileExistsError` / `FileNotFoundError` |

Seul un **socle minimal est commun** (ban `..`, confinement sous une racine, mêmes
noms d'env). Le comportement diverge sur **cinq axes** — inventaire complet, tous
à préserver à l'identique :

| Axe de divergence | audit-bim | ifc-geometry |
|---|---|---|
| **Type d'erreur** | `UnsafePathError(ValueError)` | `ValueError` / `FileExistsError` / `FileNotFoundError` |
| **Surface d'API** | `safe_input_path`, `safe_export_path`, `safe_export_read_path`, `safe_export_dir`, `get_export_root` | `safe_input_path`, `safe_output_path` |
| **Résolution des relatifs** (P2.1) | base **cwd** puis confinement | base **`AUDIT_INPUT_DIR`** |
| **Aplatissement output** (P2.2) | non (`safe_export_path` confine, `..` interdits) | oui (`safe_output_path` = `Path(name).name`) |
| **Contrôles input** | extension + **fichier régulier** + **taille max** | existence + extension **seulement** |

⚠️ Ces cinq axes ne sont **pas** unifiés en v0.1.0 : `bim-sandbox` expose une API
commune **configurable**, et chaque shim active son **profil historique** (cf. §3).

## 2. Frontière

### `bim-sandbox` contient

- Le **contrat d'env** de sandbox : `AUDIT_INPUT_DIR`, `AUDIT_OUTPUT_DIR`,
  `AUDIT_MAX_INPUT_MB` (déjà partagé entre les deux serveurs — cf. README
  ifc-geometry « aligner `AUDIT_OUTPUT_DIR` »). Le package **possède** ces
  variables ; en option, les racines peuvent aussi être passées en paramètre
  (testabilité). Aucune dépendance à un `config` applicatif.
- La **validation d'inputs** : ban `..`, confinement sous `AUDIT_INPUT_DIR`,
  whitelist d'extensions (passée par l'appelant), taille max, fichier régulier.
- La **validation d'outputs** : confinement sous `AUDIT_OUTPUT_DIR`, `..`
  interdits, gestion `overwrite`, résolution de dossier.
- L'**erreur homogène** `UnsafePathError` (**sous-classe de `ValueError`**).

### Chaque MCP garde

- Ses **valeurs par défaut métier** (ex. l'ensemble d'extensions I3F attendu par
  tel tool) — passées en paramètre, pas dans le package.
- Ses tools MCP, son wording, ses décisions.

## 3. Réconciliations & points de parité (P2)

1. **Type d'erreur → `UnsafePathError(ValueError)`.** Comme il **sous-classe déjà
   `ValueError`**, migrer ifc-geometry (qui lève aujourd'hui un `ValueError` nu)
   vers `UnsafePathError` est **non-cassant** : tout `except ValueError` existant
   continue de matcher (vérifié : les catchers des deux repos attrapent
   `ValueError`).
2. **API = union des deux.** Le package expose le sur-ensemble
   (`safe_input_path`, `safe_export_path`, `safe_export_read_path`,
   `safe_export_dir`, `safe_output_path`, `get_export_root`, `UnsafePathError`).
   Chaque repo garde ses **noms/signatures historiques** via un shim de
   ré-export — aucun call-site à réécrire.

### P2.1 — Résolution des chemins relatifs sous `AUDIT_INPUT_DIR` **diverge**

Comportement actuel, à **préserver à l'identique** (aucun changement silencieux) :

| MCP | `safe_input_path("x.pdf")` (relatif, `AUDIT_INPUT_DIR` défini) |
|---|---|
| **audit-bim** | `Path("x.pdf").resolve()` = **`<cwd>/x.pdf`**, puis doit être sous la racine (échoue si `cwd` hors racine) |
| **ifc-geometry** | `(root / "x.pdf").resolve()` = **`<AUDIT_INPUT_DIR>/x.pdf`** |

Le même relatif résout donc à des chemins **différents**. `bim-sandbox` v0.1 doit
**supporter les deux** — via un paramètre de stratégie de base (ex.
`base="cwd"` vs `base="input_root"`) ou deux fonctions — chaque shim sélectionnant
sa sémantique historique. **Pas d'harmonisation en v0.1.0.**

### P2.2 — `safe_output_path(name)` (ifc-geometry) **aplatit** le nom

Comportement actuel : `target = (root / Path(name).name).resolve()` →
`Path(name).name` **strip** sous-dossiers et traversals vers le seul nom de
fichier (« `a/b/../x.json` » → « `x.json` » sous la racine). C'est un
**aplatissement, pas un refus**. `bim-sandbox` v0.1 doit **préserver** ce
comportement dans `safe_output_path`. Ne pas le transformer en refus strict
(ça, ce serait une décision v0.2). (`safe_export_path` côté audit-bim garde sa
sémantique distincte : `..` interdits + confinement, sans aplatissement.)

### Règle des profils historiques

`bim-sandbox` expose une **API commune configurable** ; **chaque shim active le
profil historique de son MCP** — aucune convergence de comportement en v0.1.0 :

| Profil | Base relatifs | Contrôles input | Output | Erreurs |
|---|---|---|---|---|
| **audit-bim** | `base="cwd"` | extension + **fichier régulier** + **taille max** | `safe_export_path` (confinement, `..` interdits) | `UnsafePathError` |
| **ifc-geometry** | `base="input_root"` | existence + extension | `safe_output_path` (**aplati**) | `ValueError`→`UnsafePathError` (non-cassant), `FileExistsError` conservé |

La taille max et le contrôle « fichier régulier » sont **optionnels** (activés par
le profil audit-bim, désactivés par défaut / pour ifc-geometry).

## 4. Symboles à EXTRAIRE / GARDER

| Symbole | Source | Destination |
|---|---|---|
| `UnsafePathError` | audit-bim | **bim-sandbox** |
| `safe_input_path` (contrôles **paramétrables** : extension toujours ; fichier régulier + taille max = profil audit-bim uniquement) | les deux (contrôles divergents) | **bim-sandbox** (API commune + profils) |
| `safe_export_path`, `safe_export_read_path`, `safe_export_dir`, `get_export_root` | audit-bim | **bim-sandbox** |
| `safe_output_path(name)` | ifc-geometry | **bim-sandbox** |
| `ALLOWED_INPUT_EXTENSIONS` (défaut métier) | audit-bim | **reste** (défaut passé par l'appelant) |

## 5. Ordre PR

Spécificité vs read/write : **deux consommateurs** → adoption + shims **dans les
deux repos**.

1. **Merge de cette PR scope** (#39).
2. **`bim-sandbox` package pur + testé** : API union, `UnsafePathError`,
   config-agnostic (env `AUDIT_*` + params). **Tests de parité couvrant
   explicitement P2.1** (les deux modes de résolution relative) **et P2.2**
   (aplatissement `safe_output_path`), + traversal, confinement, extensions,
   taille, `overwrite` (les deux erreurs).
3. **Tag `bim-sandbox-v0.1.0`** (repo public).
4. **PR adoption `audit-bim-i3f`** : dépendance + `[tool.uv.sources]` + `uv.lock`
   + CI/release.
5. **PR shim `audit_bim/safe_paths.py`** → ré-export (mode de résolution
   `base="cwd"`).
6. **Versionner/publier proprement `ifc-geometry`** si nécessaire (adoption d'un
   package Git taggé + CI, comme audit-bim).
7. **PR adoption + shim `ifc-geometry`** → ré-export (mode `base="input_root"`,
   `safe_output_path` aplatissant ; `ValueError` → `UnsafePathError` non-cassant).

## 6. Critères de parité (gate)

**Critère central : zéro changement de comportement observable dans les deux
MCP.** En particulier :

- **P2.1 préservé** : même chemin résolu qu'avant pour un input relatif, dans
  chaque repo (cwd-based côté audit-bim, input-root-based côté ifc-geometry).
- **P2.2 préservé** : `safe_output_path` continue d'aplatir vers `Path(name).name`.
- **Décision 2 préservée** : `overwrite=False` sur fichier existant lève
  `UnsafePathError` (`safe_export_path`) ou `FileExistsError` (`safe_output_path`)
  selon la fonction, comme aujourd'hui.
- **Les deux suites** vertes : audit-bim (1007 unit + 9 integ) **et** ifc-geometry.
- **Plus aucune duplication** : les deux `safe_paths.py` deviennent des shims ;
  une seule implémentation.
- **Compatibilité des exceptions** : les `except ValueError` existants continuent
  de matcher (`UnsafePathError(ValueError)`).
- Aucun changement d'outil MCP. CI verte depuis install propre
  (`bim-sandbox@tag` public résolu) dans les deux repos.

## 7. Hors scope

- Toute nouvelle règle de sandbox ou changement de politique de confinement.
- Les défauts métier (jeux d'extensions I3F) — restent chez l'appelant.
- La sécurité MCP non liée aux chemins (`ensure_writes_allowed`, API-key,
  redaction) — reste dans `audit-bim-i3f`.
