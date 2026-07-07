# Replay A1 industrialisé (`a1_replay`)

Rejoue le protocole A1 (publication **BCF Topics + Smart Views**, `prepare →
review → apply`) avec un **verdict machine**, symétrique de l'acceptation AVP.
Scope gelé : `docs/scope-a1-replay.md`. Protocole de référence :
`docs/validation-a1-bim-publication-v0.1.0.md`.

## ⚠️ Sûreté

- **Dry-run par défaut** (aucune écriture). `--write` **uniquement** manuel.
- L'écriture réelle n'est autorisée que sur le **modèle jetable** désigné par
  `REPLAY_WRITE_MODEL_ID` — toute autre cible → refus **avant** tout `apply`.
- Contrôle d'identité par **nom exact** : le modèle actif doit être
  `DIEPPE-7427L-BATA-ARCHI-APD.ifc` (sinon refus).
- Les plans scellés + sorties restent **hors du dépôt** (refus si dans le repo).
- stdout = **compteurs / booléens / verdict** uniquement (aucune donnée client).

## Attendus déterministes (décision C, figés)

Constantes en tête de `run_replay.py` — une évolution légitime de la maquette est
un **diff d'une ligne** revu :

| | Valeur |
|---|---|
| Modèle jetable | Dieppe `1674450` (nom exact `DIEPPE-7427L-BATA-ARCHI-APD.ifc`) |
| Filtre | `error_types=[naming_invalid_format]`, `include_overview=false` |
| `EXPECTED_BCF_TOPICS` | **1** |
| `EXPECTED_SMART_VIEWS` | **1** |
| Préfixe objets | `REPLAY-BIM-PUBLICATION-YYYYMMDD — ` |

## Usage

```bash
# Cibler la maquette jetable Dieppe (nom exact contrôlé) via l'env :
export BIMDATA_MODEL_ID=1674450

# 1) Dry-run (read-only, planifiable) — prépare + revue + compte, sans écrire :
python scripts/a1_replay/run_replay.py /tmp/a1-replay

# 2) Write (manuel) — écrit sur le modèle jetable, vérifie, PUIS purge :
export REPLAY_WRITE_MODEL_ID=1674450   # garde cible jetable
python scripts/a1_replay/run_replay.py /tmp/a1-replay --write

# 2 bis) Write SANS purge — conserve les objets pour l'inspection visuelle 5b :
python scripts/a1_replay/run_replay.py /tmp/a1-replay --write --keep
```

Code de sortie 0 si `PASS`. Le dry-run PASS ne prouve pas l'écriture ; le `--write`
PASS exige `succeeded == attendu` et `failed == 0` des deux côtés **et** une purge
réussie (ou `--keep`).

## Purge automatique (create → verify → purge, un seul run)

Depuis `bimdata-write ≥ 0.1.1` (`delete_bcf_topic` / `delete_smart_view`), le
`--write` **purge les objets qu'il vient de créer** — l'écriture est d'abord
prouvée aux 3 niveaux ci-dessous, puis les topics/views au **préfixe daté de ce
run** sont supprimés et une **re-lecture indépendante** confirme qu'il n'en reste
`0`. Résultat : un `--write` **déterministe en un seul run**, sans nettoyage
manuel, la maquette jetable revenant à son état initial.

- Sélection **bornée au préfixe daté de CE run** (`REPLAY-BIM-PUBLICATION-YYYYMMDD — `) :
  jamais de suppression d'un objet hors préfixe (helper pur `select_purge_guids`,
  testé hors réseau).
- `--keep` **saute la purge** : à utiliser pour l'**inspection visuelle
  périodique 5b** (les objets restent dans le viewer). Le prochain `--write`
  same-day sans `--keep` les nettoiera (sinon le compte au préfixe daté serait `2`
  → `FAIL`).
- Une purge qui échoue (re-lecture ≠ `0`) bascule le verdict en `FAIL` : l'état
  n'est plus déterministe, on le dit plutôt que de laisser des résidus.

## Vérification post-apply (3 niveaux)

Le `--write` vérifie, **indépendamment**, à trois niveaux :

1. **rapport d'apply** — `succeeded == attendu` + `failed == 0` ;
2. **journal** (`audit_trail`) — entrée de ce run par régime, compteurs conformes ;
3. **re-lecture par l'API** (`bimdata-read ≥ 0.1.1`, `list_bcf_topics` /
   `list_smart_views`) — compte des objets au **préfixe daté de ce run** ==
   attendu. C'est ce 3ᵉ niveau qui ramène le hand-off **5b** (vérif visuelle
   viewer) d'étape obligatoire à **contrôle périodique**.

## Tests

`tests/unit/test_a1_replay_runner.py` (hors réseau) : helpers purs + les **4
refus** (confirm / intégrité de plan / cible de plan / cible jetable).
