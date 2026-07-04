# Scope — package `bim-sandbox`

Document d'architecture **figé avant tout code**. Il cartographie la sandbox de
chemins (validation inputs/outputs) **dupliquée** entre `audit-bim-i3f` et
`ifc-openshell`, fixe la frontière du package commun `bim-sandbox`, l'ordre des
PR et les critères de parité.

**Cette PR ne modifie aucun code applicatif** — inventaire et décision seulement.

Objectif : une **seule** implémentation de la sandbox de chemins, partagée par
tous les MCP, avec un comportement et des erreurs homogènes.

## 1. Constat — duplication réelle

| | `audit-bim-i3f/audit_bim/safe_paths.py` | `ifc-openshell/ifc_openshell_mcp/safe_paths.py` |
|---|---|---|
| Taille | 273 lignes (riche) | 76 lignes (minimale) |
| Confinement `..` + racine | ✅ | ✅ |
| Env | `AUDIT_INPUT_DIR`, `AUDIT_OUTPUT_DIR`, `AUDIT_MAX_INPUT_MB` | `AUDIT_INPUT_DIR`, `AUDIT_OUTPUT_DIR` |
| Inputs | `safe_input_path` (+ whitelist extensions, taille max, fichier régulier) | `safe_input_path` (whitelist extensions) |
| Outputs | `safe_export_path`, `safe_export_read_path`, `safe_export_dir`, `get_export_root` | `safe_output_path(name)` |
| Erreur | `UnsafePathError(ValueError)` | `ValueError` / `FileExistsError` / `FileNotFoundError` |

Le **cœur est identique** (ban `..`, résolution sous la racine autorisée, mêmes
noms d'env). Deux divergences seulement : le **type d'erreur** et l'**étendue de
l'API**.

## 2. Frontière

### `bim-sandbox` contient

- Le **contrat d'env** de sandbox : `AUDIT_INPUT_DIR`, `AUDIT_OUTPUT_DIR`,
  `AUDIT_MAX_INPUT_MB` (déjà partagé entre les deux serveurs — cf. README
  ifc-openshell « aligner `AUDIT_OUTPUT_DIR` »). Le package **possède** ces
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

## 3. Réconciliations (décisions)

1. **Type d'erreur → `UnsafePathError(ValueError)`.** Comme il **sous-classe déjà
   `ValueError`**, migrer ifc-openshell (qui lève aujourd'hui un `ValueError` nu)
   vers `UnsafePathError` est **non-cassant** : tout `except ValueError` existant
   continue de matcher (vérifié : les catchers des deux repos attrapent
   `ValueError`).
2. **API = union des deux.** Le package expose le sur-ensemble
   (`safe_input_path`, `safe_export_path`, `safe_export_read_path`,
   `safe_export_dir`, `safe_output_path`, `get_export_root`, `UnsafePathError`).
   Chaque repo garde ses **noms/signatures historiques** via un shim de
   ré-export — aucun call-site à réécrire.
3. **`FileExistsError` (ifc) vs `UnsafePathError`-sur-existant (audit).** Sur
   `overwrite=False` + fichier présent : conserver le comportement de chaque
   fonction (le shim ré-exporte la fonction historique). À trancher si on veut
   unifier — **recommandation : préserver** (parité stricte, pas de surprise).

## 4. Symboles à EXTRAIRE / GARDER

| Symbole | Source | Destination |
|---|---|---|
| `UnsafePathError` | audit-bim | **bim-sandbox** |
| `safe_input_path` (+ extensions/taille/fichier régulier) | les deux | **bim-sandbox** (union) |
| `safe_export_path`, `safe_export_read_path`, `safe_export_dir`, `get_export_root` | audit-bim | **bim-sandbox** |
| `safe_output_path(name)` | ifc-openshell | **bim-sandbox** |
| `ALLOWED_INPUT_EXTENSIONS` (défaut métier) | audit-bim | **reste** (défaut passé par l'appelant) |

## 5. Ordre PR

Spécificité vs read/write : **deux consommateurs** → adoption + shims **dans les
deux repos**.

0. **PR scope** — `docs/scope-bim-sandbox.md` (cette PR). Aucun code.
1. **`bim-sandbox` package pur + testé** : API union, `UnsafePathError`,
   config-agnostic (env + params). Tests offline (traversal, confinement,
   extensions, taille, overwrite, erreurs). Tag `bim-sandbox-v0.1.0`.
2. **PR adoption audit-bim-i3f** : dépendance + `[tool.uv.sources]` + `uv.lock` +
   CI/release ; puis **PR shims** `audit_bim/safe_paths.py` → ré-export.
3. **PR adoption ifc-openshell** : dépendance + CI ; puis **PR shims**
   `safe_paths.py` → ré-export (le passage `ValueError` → `UnsafePathError` est
   non-cassant).

## 6. Critères de parité (gate)

- **Les deux MCP** verts : audit-bim (1007 unit + 9 integ) **et** la suite
  ifc-openshell.
- **Plus aucune duplication** : les deux `safe_paths.py` deviennent des shims de
  ré-export ; une seule implémentation.
- **Compatibilité des exceptions** : les `except ValueError` existants continuent
  de matcher (`UnsafePathError(ValueError)`).
- Aucun changement d'outil MCP, aucun changement de comportement de confinement.
- CI verte depuis install propre (`bim-sandbox@tag` public résolu) dans les deux
  repos.

## 7. Hors scope

- Toute nouvelle règle de sandbox ou changement de politique de confinement.
- Les défauts métier (jeux d'extensions I3F) — restent chez l'appelant.
- La sécurité MCP non liée aux chemins (`ensure_writes_allowed`, API-key,
  redaction) — reste dans `audit-bim-i3f`.
