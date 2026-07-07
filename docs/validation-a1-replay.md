# Validation — replay A1 industrialisé (`--write` réel)

Preuve de la validation `--write` réelle du runner `scripts/a1_replay/run_replay.py`
sur la maquette de validation jetable **Dieppe `1674450`** (projet I3F). Politique
de données identique à l'acceptation AVP : **aucun fichier brut ni livrable client
versionné — uniquement identifiant et agrégats approuvés** ; la sortie stdout du
runner ne porte aucune donnée client.

## Contexte

Le runner a été exécuté **hors sandbox** (la sûreté = périmètre `BIMDATA_*` +
gardes du runner : `assert_write_target` + `REPLAY_WRITE_MODEL_ID` + identité par
nom exact), avec `AUDIT_BIM_ALLOW_WRITES` au défaut sûr (script direct → écritures
autorisées), `BIMDATA_MODEL_ID=1674450`, `REPLAY_WRITE_MODEL_ID=1674450`, sur
`bimdata-read v0.1.3` + `bimdata-write v0.1.1`.

## Résultat — `--write` propre en **un seul run** : PASS

Séquence `create → verify (3 niveaux) → purge → re-lecture 0`. Le `--write` a créé
sur Dieppe **1 BCF topic + 1 Smart View** au préfixe daté
`REPLAY-BIM-PUBLICATION-20260707 — `, les a vérifiés, puis les a **purgés**
automatiquement :

| Niveau de vérification | BCF | Smart View |
|---|---|---|
| **Rapport d'apply** (`succeeded`/`failed`) | 1 / 0 | 1 / 0 |
| **Journal** (`audit_trail`, entrée du run) | ✓ | ✓ |
| **Re-lecture API indépendante** (étape 8) | 1 | 1 |
| **Purge** (delete + re-lecture au préfixe = 0) | ✓ | ✓ |

Compte déterministe conforme (1 + 1), garde-fou négatif rejoué (`confirm=False` →
refus) sur les deux régimes, cible jetable + identité exacte contrôlées avant tout
apply. **Verdict PASS**, la maquette revenant à son état initial (0 objet au
préfixe daté — vérifié par re-lecture indépendante après purge).

## Bugs attrapés par la validation réelle (corrigés)

La validation `--write` réelle a attrapé **deux** écarts invisibles en dry-run.

### 1. Re-lecture Smart View = 0 — filtrage `?format` (bimdata-read)

L'endpoint topics BCF ne retourne que les issues `standard` par défaut ; les Smart
Views exigent `?format=bimdata-smartview` **côté serveur** (le listing non filtré
ne les inclut pas — vérifié contre l'API réelle). La re-lecture Smart View (étape
8) renvoyait donc `0`.

**Écart de gouvernance associé — tag déplacé.** Une première « correction » avait
été taguée `bimdata-read-v0.1.2`, mais **ce tag a été déplacé après publication**
(`497c6058` → `be43575`), en violation de « never move published tags ». Les
lockfiles restaient épinglés sur le commit *pré-correctif* (`497c6058`, filtrage
client-side) : `uv sync` réinstallait donc silencieusement le code cassé, et
`list_smart_views()` renvoyait toujours `0`. La correction a été **re-publiée
proprement sous un tag immuable `bimdata-read-v0.1.3`** (filtrage `?format=` côté
serveur ; `v0.1.2` proscrite, cf. README bimdata-read « Versions »).
**Vérifié contre l'API réelle** : `list_smart_views()` retrouve alors les Smart
Views (`api_verify` = 1 / 1).

### 2. Objets résiduels non purgés

Tant que `list_smart_views()` renvoyait `0`, l'auto-purge (ci-dessous) ne « voyait »
pas les Smart Views créées → elles restaient orphelines sur la maquette. Une purge
de rattrapage (guidée par le listing serveur `?format=bimdata-smartview`, garde
anti-collatéral) a nettoyé **2 BCF standard + 3 Smart Views** REPLAY résiduelles ;
les topics/vues **réels** du projet (5 BCF + 7 Smart Views) sont restés intacts.
Cette purge a **validé `delete_bcf_topic` ET `delete_smart_view` contre l'API
réelle**.

## Purge automatique (create → verify → purge)

Depuis `bimdata-write v0.1.1` (`delete_bcf_topic` / `delete_smart_view`), le
`--write` **purge les objets qu'il crée** après les avoir prouvés aux 3 niveaux,
puis re-vérifie qu'il ne reste `0` objet au préfixe daté de ce run. Sélection
**bornée au préfixe daté** (helper pur `select_purge_guids`) ; `--keep` conserve
les objets pour l'inspection visuelle périodique 5b ; une purge incomplète bascule
le verdict en `FAIL`. Détail : `scripts/a1_replay/README.md`. La procédure de purge
manuelle du viewer reste le **repli** documenté.

## Portée du hand-off 5b

La re-lecture API indépendante (étape 8) + l'auto-purge étant en place et prouvées,
la vérif visuelle viewer **5b** passe d'étape obligatoire de chaque replay à
**contrôle périodique** (à lancer avec `--keep` pour conserver les objets).
