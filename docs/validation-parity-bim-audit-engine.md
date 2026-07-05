# Validation de parité — extraction `bim-audit-engine` (v0.5.2)

Preuve empirique que le passage du moteur d'audit en dur à la **façade** sur le
package `bim-audit-engine` (#63 adoption + #64 façade) ne change **aucun**
résultat observable, sur une **maquette I3F réelle**, **sans aucune écriture
BIMData** (replay read-only).

## Protocole

Même **snapshot** et même **catalogue** injectés dans les deux versions du
moteur, puis comparaison exhaustive de la sortie.

| Paramètre | Valeur |
|---|---|
| Modèle | `250613_MN_BAT.ifc` — projet **I3F** (réel) |
| Taille snapshot | 1 site / 1 bâtiment / 10 étages / 316 espaces / 24 zones / **10 549 éléments** |
| Catalogue | CCH **3.6** réel (build depuis les 3 documents MOA : Cahier des annexes PDF + annexes « Spécification des données » V3.7 et « Nommage » V3.6) — 1018 propriétés, 7 règles de nommage, 21 étages, 30 zones, 72 pièces |
| Phase | `AVP` |
| Ancien moteur | commit `65ac0c9` (adoption infra, moteur **en dur**, `AuditResult` local) |
| Nouveau moteur | master (façade, `AuditResult` ré-exporté de `bim_audit_engine`) |
| Écritures BIMData | **aucune** (extraction + audit uniquement) |

Le snapshot et le catalogue sont extraits **une seule fois** puis sérialisés
(`snapshot.json` via `dataclasses.asdict`, `catalog.json` via
`model_dump_json`), et rechargés à l'identique par chaque version — exécutée
depuis son propre worktree pour garantir que `run_audit` provient bien de la
version testée.

Discriminant de version vérifié dans le dump :
`AuditResult.__module__` = `audit_bim.audit.engine` (ancien) vs
`bim_audit_engine.result` (nouveau).

## Résultat — PARITÉ EXACTE ✅

| Comparaison | Verdict |
|---|---|
| `n_findings` | **49 798** = 49 798 ✅ |
| `phase` | ✅ |
| `summary()` | ✅ |
| `count_by_severity` | ✅ |
| `count_by_theme` | ✅ |
| `count_by_error_type` | ✅ |
| `count_by_ifc_type` | ✅ |
| `conformity_rate` | ✅ |
| **Liste des findings — ordre + chaque `Finding.model_dump()`** (hash SHA-256 de la liste complète) | ✅ identique |

Les 49 798 findings sont **strictement identiques**, dans le **même ordre**, avec
le **même contenu sérialisé**, et tous les agrégats coïncident. L'extraction du
moteur est donc **sans effet observable**.

## Reproduire

Harnais versionné : `scripts/engine_parity/` (voir son `README.md`). Les artefacts
(`snapshot.json`, `catalog.json`, `new.json`, `old.json`) contiennent des **données
client** et **ne sont jamais versionnés** — les scripts refusent d'écrire dans le
dépôt ; écrire **hors du repo** (`$OUT`).

```bash
OUT=/tmp/engine-parity                                     # HORS du repo
# 1. Artefacts réels (une fois, depuis master + venv configuré)
python scripts/engine_parity/extract_artifacts.py "$OUT"
# 2. Nouveau moteur (master / façade)
python scripts/engine_parity/replay.py "$OUT" "$OUT/new.json"
# 3. Ancien moteur (worktree pré-façade, ex. 65ac0c9)
git worktree add /tmp/wt-old 65ac0c9
cd /tmp/wt-old && python <repo>/scripts/engine_parity/replay.py "$OUT" "$OUT/old.json"
# 4. Verdict — hashes / compteurs / booléens uniquement (exit 0 = parité)
python scripts/engine_parity/compare.py "$OUT/new.json" "$OUT/old.json"
```

La logique de `compare.py` est couverte par un test synthétique en CI :
`tests/unit/test_engine_parity_compare.py`.
