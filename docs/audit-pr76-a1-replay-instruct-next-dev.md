# Audit PR #76 (replay A1 — étape 1) + instruction pour le prochain dev

Audit de `feat/a1-replay-runner` (PR #76, `492d1f0`) contre le scope gelé
`docs/scope-a1-replay.md`, exécuté sur la branche (suite complète + ruff), puis
instruction ordonnée pour la suite du jalon.

## Verdict

**GO pour merge, avec 1 correctif P2 à faire avant (ou en fast-follow immédiat)
et 3 P3 au fil de l'eau.** Vérifié localement sur la branche : **1090 passed +
5 skipped (= 1095 collectés)**, ruff clean — les chiffres de la PR sont exacts.

## Conformité au scope gelé — vérifiée

- **Séquence 1–7 et 10** implémentées : contrôle d'identité, garde cible jetable
  (`assert_write_target`, `SystemExit` avant tout `apply`), audit réel avec
  `build_catalog` + refus catalogue vide, plans scellés hors repo
  (`_assert_outside_repo` + `AUDIT_OUTPUT_DIR`), revue `inspect_plan` (helper pur
  partagé runner ↔ tests), garde-fou négatif rejoué, `--write` explicite /
  dry-run par défaut, verdict 0/1, stdout compteurs/booléens sans donnée client.
- **Décisions figées appliquées** : A (procédure de purge versionnée dans le
  README du runner, auto-delete renvoyé au suivi borné `bimdata-write`),
  B (dry-run planifiable / `--write` manuel), C (constantes nommées
  `EXPECTED_BCF_TOPICS=1` / `EXPECTED_SMART_VIEWS=1` + modèle + filtre en tête de
  fichier — le diff-d'une-ligne demandé au gel est respecté).
- **Les 4 refus** prouvés hors réseau (12 tests), dont un **vrai** scellé altéré
  après `save_plan` → `PlanIntegrityError`.
- **Non-buts respectés** : aucun nouveau tool MCP, aucune modification de
  `bim-publication`/builders, aucune écriture hors modèle jetable.
- **Dry-run réel PASS** sur Dieppe `1674450` (1 topic + 1 view == attendus).

## Écarts relevés

### P2 — Étape 9 (journal) non implémentée, README sur-vendeur

Le scope gèle l'étape 9 : « Journal — entrées `audit_trail` présentes,
`succeeded/failed` conformes ». Le runner vérifie `succeeded/failed` **depuis le
résultat d'apply seulement** et ne lit jamais le journal ; le README affirme
pourtant « rapport d'apply + `audit_trail` ». Le mécanisme existe
(`get_journal().tail()`, cf. `audit_bim/mcp/tools_actions.py::audit_trail`).

**Correctif attendu** (chemin Python, pas MCP — conforme au non-but) : après les
deux apply en `--write`, relire `get_journal().tail(n=...)`, vérifier qu'on y
trouve les entrées `apply_bcf_topics` / `apply_smart_views` du run avec
`succeeded/failed` conformes, ajouter les booléens au rapport et les intégrer au
verdict. Sinon, à défaut, corriger le README — mais l'étape 9 est gelée, donc la
première option est la bonne.

### P3 (au fil de l'eau, non bloquants)

1. **Garde-fou négatif rejoué sur BCF seulement** — le protocole prouvé
   (`validation-a1-bim-publication-v0.1.0.md` §5) rejouait les **deux** refus.
   Ajouter `apply_smart_views_plan(confirm=False)` → `refused: true`.
2. **Contrôle d'identité par fragment** (`"DIEPPE" in name`) là où le scope dit
   « le nom de modèle attendu doit matcher ». Risque faible en écriture (la
   garde `REPLAY_WRITE_MODEL_ID` verrouille), mais un dry-run peut cibler une
   autre maquette « Dieppe » sans le signaler autrement que par le compte.
   Durcir vers un nom attendu exact (constante) ou documenter le choix.
3. **Contrôle `_missing` des documents I3F placé après `build_catalog`** — si un
   document manque, `build_catalog` échoue avant que le refus lisible ne serve.
   Déplacer le contrôle avant l'appel.

### Écart déclaré (accepté) — étape 8 en deux temps

La **relecture indépendante post-apply par l'API** (re-lister topics/views créés :
compte + préfixe + cible) exige un endpoint de liste absent de `bimdata-read`.
L'écart est **déclaré** (PR, README, note dans le code) et la v1 vérifie
`succeeded == attendu` + `failed == 0`. Accepté comme **prérequis borné** : tant
que l'endpoint n'existe pas, le hand-off 5b (vérif visuelle) reste obligatoire
après un `--write` — c'est précisément ce que l'étape 8 doit faire disparaître,
donc l'endpoint est sur le chemin critique de la clôture du jalon.

## Instruction — ordre d'exécution pour le prochain dev

1. **Correctif P2 (étape 9 journal)** sur la branche de la PR #76, puis merge.
   Les P3 peuvent suivre dans la même PR ou une petite PR dédiée.
2. **`bimdata-read` : endpoints de liste read-only** (`list_bcf_topics`,
   `list_smart_views` — GET seulement, mêmes gardes de confidentialité que le
   reste du package). C'est le prérequis borné de l'étape 8.
3. **Brancher l'étape 8 complète** dans le runner : après apply, re-lister via
   l'API et vérifier **compte + préfixe + cible** indépendamment du rapport
   d'apply. À partir de là, 5b devient un contrôle périodique (conforme au gel).
4. **Validation `--write` réelle** sur Dieppe `1674450` : doc
   `docs/validation-a1-replay-<version>.md` (identifiants + agrégats seulement),
   puis **purge** selon la procédure du README (le dry-run suivant doit rester
   déterministe à 1 + 1).
5. Ensuite seulement : chantier secondaire **`field_path` non-zone** (figer le
   format `<ClasseIfc>.<Attribut>` / `<ClasseIfc>.<Pset>.<Propriété>` d'abord,
   liste d'exemptions explicite, verrou générique sur `I3F_RULES`).

**Rappels gelés** : pas de release tant que dry-run **et** write ne sont pas
PASS sur le réel ; aucune donnée client versionnée ; le compte attendu reste
asserté en exact (toute dérive = signal, pas un PASS silencieux).
