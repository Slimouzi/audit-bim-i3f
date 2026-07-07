# Instruction CTO — clôture du jalon « replay A1 industrialisé »

Instruction d'exécution **gelée** pour terminer le jalon A1 (industrialisation
de `prepare → review → apply` BCF / Smart Views) jusqu'à la **preuve `--write`
réelle** qui débloque la release. Fait suite à :

- l'instruction de cadrage `docs/instruct-a1-replay-industrialisation.md` (9ae679f) ;
- le scope gelé `docs/scope-a1-replay.md` (décisions A/B/C figées) ;
- l'audit d'étape 1 `docs/audit-pr76-a1-replay-instruct-next-dev.md` (PR #76).

**État à date** : PR #76 (`feat/a1-replay-runner`, `492d1f0`) apporte la CI
hors-ligne (helpers purs + 4 refus, 12 tests) et le dry-run réel PASS. Suite
complète verte (1090 passed + 5 skipped), ruff clean. Il reste : 1 P2, 3 P3, la
vérif post-apply indépendante (étape 8), la preuve `--write`, puis le chantier
secondaire `field_path`.

---

## 1. Décision d'environnement (gelée)

Le replay A1 (dry-run **et** `--write`) et l'acceptation AVP sont des tests
**réseau réels**. Un environnement sandboxé (réseau isolé + variables d'env
vidées) ne peut, par construction, prouver ni le dry-run réel ni le `--write` —
il **bloque** donc le gel « pas de release tant que le write n'a pas prouvé
PASS ».

**Décision** : exécuter le prochain dev **hors sandbox**, tests au réel **sur le
seul périmètre exposé par les variables d'environnement** (`BIMDATA_API_KEY` /
`BIMDATA_CLIENT_ID` / `BIMDATA_CLIENT_SECRET` / `BIMDATA_CLOUD_ID` /
`BIMDATA_PROJECT_ID` / `BIMDATA_MODEL_ID`, cf. `.env.example`).

**La borne de sûreté est le périmètre env + les gardes du runner**, pas le
sandbox :

- `assert_write_target` + `REPLAY_WRITE_MODEL_ID` verrouillent l'écriture sur le
  seul modèle jetable (Dieppe `1674450`) — toute autre cible → refus **avant**
  tout `apply` ;
- le contrôle d'identité rejette une maquette dont le nom ne matche pas ;
- restent en vigueur hors sandbox : dry-run par défaut, `--write` **manuel**
  uniquement, plans/sorties hors repo, stdout sans donnée client, purge
  documentée après chaque `--write`.

Le sandbox n'ajoute aucune sûreté ici ; il empêche seulement la preuve. La
bascule est un réglage de l'environnement d'exécution (politique réseau Claude
Code on the web) — hors dépôt, à opérer côté plateforme.

## 2. Ordre d'exécution (gelé)

### Étape 0 — environnement hors sandbox
Condition nécessaire (cf. §1). Vérifier l'accès : `BIMDATA_*` présents,
connectivité `api.bimdata.io`, modèle actif = Dieppe `1674450`.

### Étape 1 — correctifs runner sur `feat/a1-replay-runner`, puis merge PR #76
- **P2 (bloquant, étape 9 gelée)** : après les deux `apply` en `--write`, relire
  le journal (`get_journal().tail(n=...)`, cf.
  `audit_bim/mcp/tools_actions.py::audit_trail`), vérifier la présence des
  entrées `apply_bcf_topics` / `apply_smart_views` du run avec `succeeded/failed`
  conformes, ajouter les booléens au rapport **et au verdict**. Chemin Python
  (pas MCP) — conforme au non-but.
- **P3-a** : rejouer le garde-fou négatif aussi sur les Smart Views
  (`apply_smart_views_plan(confirm=False)` → `refused: true`), comme le
  protocole prouvé §5.
- **P3-b** : contrôle d'identité par **nom attendu exact** (constante) plutôt que
  fragment `"DIEPPE"`, ou documenter explicitement le choix du fragment.
- **P3-c** : déplacer le contrôle `_missing` des documents I3F **avant**
  `build_catalog` pour que le refus lisible serve.
- Suite complète verte + ruff clean → merge.

### Étape 2 — `bimdata-read` : endpoints de liste read-only
`list_bcf_topics` / `list_smart_views` (GET seulement, mêmes gardes de
confidentialité que le reste du package). Prérequis borné de l'étape 8.

### Étape 3 — brancher l'étape 8 complète dans le runner
Après apply en `--write`, **re-lister via l'API** et vérifier **indépendamment**
du rapport d'apply : **compte + préfixe + cible**. C'est cette relecture qui
ramène le hand-off 5b (vérif visuelle) d'obligatoire à **contrôle périodique**.

### Étape 4 — preuve réelle + validation versionnée
Sur Dieppe `1674450`, hors sandbox :
1. **Dry-run PASS** (read-only) — confirme 1 topic + 1 view attendus ;
2. **`--write` PASS** (manuel, décision B) — `export REPLAY_WRITE_MODEL_ID=1674450`
   puis `run_replay.py <out_hors_repo> --write` ; verdict = `succeeded == attendu`
   + `failed == 0` + journal conforme (P2) + relecture API conforme (étape 3) ;
3. **doc de validation** `docs/validation-a1-replay-<version>.md` — identifiants
   + agrégats **seulement**, aucune donnée client ;
4. **purge** selon la procédure du README du runner (préfixe daté) ; le dry-run
   suivant doit rester déterministe à **1 + 1**.

### Étape 5 — chantier secondaire `field_path` non-zone (au fil de l'eau)
Non bloquant pour la clôture A1. **Figer le format d'abord** (contrat de fait) :
`"<ClasseIfc>.<Attribut>"` (natifs) / `"<ClasseIfc>.<Pset>.<Propriété>"` (Psets) ;
findings **projet** sans attribut → `None` avec **liste d'exemptions explicite**.
Émission : `naming.py` (espaces, étages), `properties.py`, `classifications.py`,
`uniqueness.py`, `spatial.py`, `lists.py`. **Verrou** : test générique « tout
finding émis par `I3F_RULES` porte un `field_path` non nul sauf exemptions ». Ne
pas généraliser la **consommation** sans consommateur réel.

## 3. Décisions figées rappelées (A/B/C — inchangées)

- **A. Nettoyage** : pas d'auto-delete v1 (`bimdata-write` n'a pas de `delete_*`,
  `bim-publication` intouchable) → préfixe daté + purge documentée. Auto-delete =
  suivi ultérieur borné (ajout de `delete_*` dans `bimdata-write`).
- **B. Fréquence** : dry-run planifiable (read-only) ; `--write` **manuel**
  uniquement, déclenché par un humain.
- **C. Compteur déterministe** : cible + filtre figés (Dieppe `1674450`,
  `error_types=[naming_invalid_format]`, `include_overview=false`) → attendu
  **exact 1 topic + 1 Smart View**, asserté par constantes nommées. Toute dérive
  = **signal**, jamais un PASS silencieux.

## 4. Non-buts

- Aucun nouveau tool MCP côté serveur (réutiliser les chemins Python
  `prepare_*` / `apply_*`) ; **exception cadrée** : les GET read-only
  `list_bcf_topics` / `list_smart_views` de l'étape 2 sont autorisés (lecture
  seule, prérequis de la vérif indépendante).
- Aucune modification de `bim-publication` ni des builders.
- Aucune écriture hors du modèle jetable.
- Pas de release tant que dry-run **et** `--write` ne sont pas PASS sur le réel.
- Pas de généralisation de la consommation `field_path` sans consommateur.

## 5. Critères de clôture du jalon (= porte de release)

1. PR #76 mergée avec P2 + les 3 P3 ; suite complète verte, ruff clean.
2. `bimdata-read` expose les deux GET de liste, testés.
3. Runner : étape 8 (relecture API indépendante) branchée ; étape 9 (journal)
   intégrée au verdict.
4. **Dry-run réel PASS puis `--write` réel PASS** sur Dieppe `1674450`, doc de
   validation versionné (identifiants + agrégats seulement), objets purgés.
5. Les **4 refus** toujours prouvés par tests ; aucune donnée client versionnée.

Une fois 1–5 remplis : la release du jalon A1 est débloquée. `field_path`
non-zone suit au fil de l'eau, hors chemin critique.

## 6. Registre de dette (inchangé)

Cf. `docs/audit-avp-acceptance-instruct-field-path.md` §4 : (a) retrait de
l'override uv après bump des transitifs ; (b) wording « immuable »
`bim_audit_engine/result.py`. La dette **(c) CI bim-core est close**
(`Slimouzi/bim-core#2`) — hors chemin.
