# Replay A1 industrialisé (`a1_replay`)

Rejoue le protocole A1 (publication **BCF Topics + Smart Views**, `prepare →
review → apply`) avec un **verdict machine**, symétrique de l'acceptation AVP.
Scope gelé : `docs/scope-a1-replay.md`. Protocole de référence :
`docs/validation-a1-bim-publication-v0.1.0.md`.

## ⚠️ Sûreté

- **Dry-run par défaut** (aucune écriture). `--write` **uniquement** manuel.
- L'écriture réelle n'est autorisée que sur le **modèle jetable** désigné par
  `REPLAY_WRITE_MODEL_ID` — toute autre cible → refus **avant** tout `apply`.
- Contrôle d'identité : le modèle actif doit contenir `DIEPPE` (sinon refus).
- Les plans scellés + sorties restent **hors du dépôt** (refus si dans le repo).
- stdout = **compteurs / booléens / verdict** uniquement (aucune donnée client).

## Attendus déterministes (décision C, figés)

Constantes en tête de `run_replay.py` — une évolution légitime de la maquette est
un **diff d'une ligne** revu :

| | Valeur |
|---|---|
| Modèle jetable | Dieppe `1674450` (identité `DIEPPE`) |
| Filtre | `error_types=[naming_invalid_format]`, `include_overview=false` |
| `EXPECTED_BCF_TOPICS` | **1** |
| `EXPECTED_SMART_VIEWS` | **1** |
| Préfixe objets | `REPLAY-BIM-PUBLICATION-YYYYMMDD — ` |

## Usage

```bash
# Cibler la maquette jetable Dieppe (identité DIEPPE) via l'env :
export BIMDATA_MODEL_ID=1674450

# 1) Dry-run (read-only, planifiable) — prépare + revue + compte, sans écrire :
python scripts/a1_replay/run_replay.py /tmp/a1-replay

# 2) Write (manuel) — écrit sur le modèle jetable désigné :
export REPLAY_WRITE_MODEL_ID=1674450   # garde cible jetable
python scripts/a1_replay/run_replay.py /tmp/a1-replay --write
```

Code de sortie 0 si `PASS`. Le dry-run PASS ne prouve pas l'écriture ; le `--write`
PASS exige `succeeded == attendu` et `failed == 0` des deux côtés.

## Procédure de purge (décision A — pas d'auto-delete en v1)

`bimdata-write` n'expose pas de méthode de suppression et `bim-publication` est
intouchable → **pas d'auto-delete en v1**. Les objets créés portent le préfixe
daté `REPLAY-BIM-PUBLICATION-YYYYMMDD — `. **Purge manuelle** sur le modèle
jetable :

1. Ouvrir le viewer BIMData du modèle jetable (Dieppe `1674450`).
2. Panneau **BCF Issues** : filtrer/supprimer les topics dont le titre commence
   par `REPLAY-BIM-PUBLICATION-` ; panneau **Smart Views** : idem pour les vues.
3. Vérifier qu'aucun objet préfixé ne subsiste (le prochain dry-run doit rester
   déterministe).

> **Suivi ultérieur borné** : ajouter des méthodes `delete_*` dans `bimdata-write`
> (le transport authentifié gère déjà `DELETE`, cf. `docs/scope-bimdata-write.md`)
> pour automatiser cette purge — hors scope v1.

## Vérification post-apply (état v1)

Le `--write` vérifie `succeeded == attendu` + `failed == 0` (rapport d'apply +
`audit_trail`). La **relecture indépendante par l'API** (lister les topics/views
créés pour re-vérifier compte + préfixe + cible) exige un **endpoint de liste
absent de `bimdata-read`** — prérequis borné à ajouter (cf. scope §4). Tant qu'il
n'existe pas, le hand-off 5b (vérif visuelle viewer) reste recommandé après un
`--write`.

## Tests

`tests/unit/test_a1_replay_runner.py` (hors réseau) : helpers purs + les **4
refus** (confirm / intégrité de plan / cible de plan / cible jetable).
