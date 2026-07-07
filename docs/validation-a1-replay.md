# Validation — replay A1 industrialisé (`--write` réel)

Preuve de la validation `--write` réelle du runner `scripts/a1_replay/run_replay.py`
sur la maquette de validation jetable **Dieppe `1674450`** (projet I3F). Politique
de données identique à l'acceptation AVP : **aucun fichier brut ni livrable client
versionné — uniquement identifiant et agrégats approuvés** ; la sortie stdout du
runner ne porte aucune donnée client.

## Contexte

Le runner a été exécuté **hors sandbox** (la sûreté = périmètre `BIMDATA_*` +
gardes du runner : `assert_write_target` + `REPLAY_WRITE_MODEL_ID` + identité par
nom exact), avec `AUDIT_BIM_ALLOW_WRITES=true`, `BIMDATA_MODEL_ID=1674450`,
`REPLAY_WRITE_MODEL_ID=1674450`.

## Résultat — écriture réelle **réussie**, vérifiée à 3 niveaux

Le `--write` a créé sur Dieppe **1 BCF topic + 1 Smart View** au préfixe daté
`REPLAY-BIM-PUBLICATION-20260707 — ` :

| Niveau de vérification | BCF | Smart View |
|---|---|---|
| **Rapport d'apply** (`succeeded`/`failed`) | 1 / 0 | 1 / 0 |
| **Journal** (`audit_trail`, entrée du run) | ✓ | ✓ |
| **Re-lecture API indépendante** (étape 8) | 1 | 1 |

Compte déterministe conforme (1 + 1), garde-fou négatif rejoué (`confirm=False` →
refus) sur les deux régimes, cible jetable + identité exacte contrôlées avant tout
apply.

### Bug attrapé par la validation réelle (corrigé)

Le **premier** `--write` a rendu un verdict FAIL : la re-lecture Smart View (étape
8) renvoyait 0. Cause : l'endpoint topics BCF ne retourne que les issues
`standard` par défaut — les Smart Views exigent `?format=bimdata-smartview`. Le
filtrage était fait côté client dans `bimdata-read` v0.1.1. **Corrigé en
`bimdata-read v0.1.2`** (filtrage côté serveur par query param), **vérifié contre
l'API réelle** : la re-lecture retrouve alors la Smart View (`api_verify` = 1 / 1).
C'est précisément le rôle de la validation `--write` réelle d'attraper ce type
d'écart invisible en dry-run.

## Purge (décision A — pas d'auto-delete en v1)

Les objets créés doivent être purgés **manuellement** (pas de `delete_*` dans
`bimdata-write`). À supprimer dans le viewer du modèle jetable Dieppe `1674450` :

- **BCF Issues** : le topic `REPLAY-BIM-PUBLICATION-20260707 — Nommage Pièce`.
- **Smart Views** : la vue `REPLAY-BIM-PUBLICATION-20260707 — Nommage Pièce`.

Après purge, un prochain `--write` (même date) repart d'un état déterministe.
Procédure détaillée : `scripts/a1_replay/README.md` (section « Procédure de
purge »).

## Portée du hand-off 5b

La re-lecture API indépendante (étape 8) étant en place et prouvée, la vérif
visuelle viewer **5b** passe d'étape obligatoire de chaque replay à **contrôle
périodique**.
