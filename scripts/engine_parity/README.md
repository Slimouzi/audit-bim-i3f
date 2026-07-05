# Harnais de parité moteur (`engine_parity`)

Reproduit la preuve de `docs/validation-parity-bim-audit-engine.md` : le moteur
en façade (`audit_bim.audit.engine` → `bim-audit-engine`) produit **exactement**
les mêmes résultats que l'ancien moteur en dur, sur une maquette I3F réelle.

## ⚠️ Données client — ne jamais versionner

`extract_artifacts.py` et `replay.py` produisent des fichiers qui contiennent des
**données client** (snapshot du modèle, catalogue, `Finding.model_dump()`). Ils
**ne doivent jamais** entrer dans le dépôt :

- les deux scripts **refusent** d'écrire à l'intérieur du repo (garde
  `_assert_outside_repo`) → écris les artefacts **hors du repo**, ex.
  `/tmp/engine-parity` ;
- `scripts/engine_parity/.gitignore` ignore tout `*.json` par précaution.

Seul `compare.py` produit une sortie **sûre à archiver** : uniquement des
empreintes SHA-256, des compteurs, des booléens et un verdict — **aucun** contenu
de finding.

## Procédure

```bash
OUT=/tmp/engine-parity                      # HORS du repo

# 1. Artefacts réels (une fois, depuis master + venv configuré)
python scripts/engine_parity/extract_artifacts.py "$OUT"

# 2. Nouveau moteur (master / façade)
python scripts/engine_parity/replay.py "$OUT" "$OUT/new.json"

# 3. Ancien moteur (worktree d'un commit pré-façade, ex. 65ac0c9)
git worktree add /tmp/wt-old <commit-pre-facade>
cd /tmp/wt-old && python <repo>/scripts/engine_parity/replay.py "$OUT" "$OUT/old.json"

# 4. Verdict (hashes / compteurs / booléens uniquement)
python scripts/engine_parity/compare.py "$OUT/new.json" "$OUT/old.json"
```

`compare.py` sort en code 0 si parité exacte, 1 sinon. `replay.py` résout
`audit_bim` depuis le **CWD** : lance-le depuis le worktree de la version à tester.

## Test

La logique de `compare.py` est couverte par un test **synthétique** (données
factices, aucune donnée client) :
`tests/unit/test_engine_parity_compare.py` — exécuté en CI.
