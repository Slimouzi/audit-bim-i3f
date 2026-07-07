# Instruction CTO — audit des branches, hygiène de merge, et suites (post-A1)

Audit de **toutes les branches** du dépôt après la clôture du jalon replay A1
(PR #76–#80 mergées, `--write` PASS en un run, auto-purge validée,
remédiation moved-tag `bimdata-read v0.1.3`, sweep d'intégrité des 7 tags).
Verdicts de merge branche par branche, puis instructions : release, gel
`field_path` (§2 tranché), dette.

Méthode : pour chaque branche, comparaison **de contenu** avec master (pas
seulement ahead/ahead — les squash-merges créent des « ahead » fantômes),
lecture des commits non mergés, croisement avec l'état des PRs.

## 1. Verdicts par branche

| Branche | État vérifié | Verdict |
|---|---|---|
| `master` | `ba75ab8`, sain, jalon A1 clos | référence |
| `claude/avp-acceptance-audit-naa958` | seul contenu non mergé : `docs/instruct-a1-replay-industrialisation.md` (9ae679f) — **référencé par `docs/scope-a1-replay.md` sur master → référence pendante** | **MERGE partiel** (le doc), puis delete |
| `claude/perspective-sharing-cursor-follow-02xy1m` | 5 commits docs : 2 docs de gouvernance A1 (audit PR #76, instruction de clôture) + le prompt visionneuse (hors-mission dépôt) | **MERGE partiel** (les 2 docs A1), puis delete |
| `codex/actionable-selection-viewer-smartview` | ahead 0 — intégralement mergée (#28) | **DELETE** |
| `codex/select-bim-objects` | ahead 0 — intégralement mergée | **DELETE** |
| `docs/validation-a1-bim-publication` | ahead 1 mais **contenu identique** à master (doc déjà mergé par ailleurs) | **DELETE** |
| `codex/mcp-setup-web` | ahead 1, **86 behind**, 2026-06-26 : page web `/mcp-setup` + sessions BIMData tokenisées (~1 470 lignes), aucune PR ouverte | **NE PAS MERGER** — archiver puis delete (cf. §1.3) |

### 1.1 Récupérer l'instruction A1 pendante (P2 — référence cassée sur master)

`docs/scope-a1-replay.md` (master) référence
`docs/instruct-a1-replay-industrialisation.md`, qui n'existe **que** sur
`claude/avp-acceptance-audit-naa958` (9ae679f). Le reste de la branche
(d8de45f) est déjà sur master via #74 (squash).

**Instruction** : branche fraîche depuis master → cherry-pick du seul 9ae679f
(ou copie du fichier) → PR docs-only → merge → `git push origin --delete
claude/avp-acceptance-audit-naa958`.

### 1.2 Versionner la piste de décision A1 (docs de gouvernance)

Même mécanique pour `claude/perspective-sharing-cursor-follow-02xy1m` : PR
docs-only portant **uniquement** `docs/audit-pr76-a1-replay-instruct-next-dev.md`
et `docs/instruct-a1-replay-closeout.md` (la piste audit → instruction →
exécution du jalon, même discipline que les docs AVP). Le
`docs/prompt-viewpoint-sharing-follow-mode.md` est **hors mission** de ce dépôt
(visionneuse BIMData) : ne pas le merger sur master — il rejoindra le dépôt de
la visionneuse quand ce chantier ouvrira. Puis delete de la branche.

### 1.3 `codex/mcp-setup-web` — clore sans merger

86 commits de retard, aucune PR, et une surface **sensible** (sessions BIMData
tokenisées exposées en web) qui exigerait de toute façon un passage par la
discipline scope-gelé + revue sécurité. Un rebase de ~1 470 lignes sur 86
commits coûte plus cher qu'une réécriture cadrée.

**Instruction** : tag d'archive `archive/codex-mcp-setup-web` sur `8c2cbed`
(l'historique reste retrouvable), puis delete de la branche. Si le besoin
`/mcp-setup` revient, il redémarre **de master** par une instruction + scope
gelé, comme tout chantier.

### 1.4 Commandes (après merge des 2 PRs docs-only)

```bash
git tag archive/codex-mcp-setup-web 8c2cbed && git push origin archive/codex-mcp-setup-web
git push origin --delete codex/mcp-setup-web codex/actionable-selection-viewer-smartview \
  codex/select-bim-objects docs/validation-a1-bim-publication \
  claude/avp-acceptance-audit-naa958 claude/perspective-sharing-cursor-follow-02xy1m
```

Cible finale : `master` seul + branches de travail vivantes. Zéro branche morte.

## 2. Release — la porte est levée

Le gel disait : « pas de release tant que dry-run **et** write ne sont pas PASS
sur le réel ». Les 5 critères de clôture (`docs/instruct-a1-replay-closeout.md`
§5) sont remplis, plus l'auto-purge et la remédiation moved-tag.

**Instruction** : après l'hygiène §1 (pour que la release embarque la piste de
décision complète), **release mineure `v0.7.0`** — replay A1 industrialisé
(runner 3 niveaux + auto-purge), `bimdata-read v0.1.3` / `bimdata-write v0.1.1`,
CHANGELOG, même pipeline que 0.6.0 (smoke-install compris). La v0.7.0 fige
l'état « A1 clos » avant d'ouvrir le chantier field_path.

## 3. Chantier #5 — `field_path` non-zone : décisions

### §2 tranché : None-exempt, pas de pseudo-champs

Les findings **classification-defect** et **spatial-orphan** sont exemptés à
`None`. On n'invente pas de token relationnel (`IfcSpace.SpatialContainment`) :

- la grammaire gelée est un contrat « champ résoluble sur le modèle IFC »
  (attribut / Pset / Qto). Un token relationnel **ressemble** à un attribut mais
  n'en est pas un — chaque consommateur devrait le traiter en cas particulier,
  ce qui est pire qu'un `None` explicite ;
- le principe gelé « pas de consommateur spéculatif » s'applique : aucun
  consommateur n'a besoin de discriminer ces findings aujourd'hui ;
- réversible à coût borné : si un consommateur réel apparaît, on **étend la
  grammaire délibérément** (famille de tokens relationnels dédiée, gelée à ce
  moment-là) — promotion d'une exemption = diff scopé et revu.

**Amendement au scope avant gel** : la whitelist d'exemptions est **par
`error_type`** (pas par famille de règles), et chaque entrée porte une
justification d'une ligne dans le tableau §3 — la whitelist ne peut pas grossir
silencieusement.

### Process

Oui — **PR docs-only, voie habituelle**. Pousse `docs/scope-field-path.md`
(avec l'amendement ci-dessus intégré) ; je gèle §1–§3 en revue ; ensuite
émission + verrou générique. Le verrou proposé (grammaire ∨ (None ∧ exempté),
sinon CI rouge) est exactement le bon : il rend toute omission **visible**.

## 4. Dette — GO cadré

- **Retrait des 2 `override-dependencies` uv** : GO, mais **pas
  opportunistiquement au fil d'une PR** — c'est du cross-repo. Ordre : bumper
  les transitifs (`bimdata-write`, `bim-query`, `bim-publication`) pour épingler
  `bim-core v0.1.1` + `bimdata-read v0.1.3` sous **nouveaux tags immuables** ;
  **vérifier chaque nouveau tag contre le rev du lock** (réflexe post-incident —
  rejouer le sweep d'intégrité) ; puis PR dédiée ici qui retire les overrides,
  avec `uv lock --check` + suite complète. Une PR, un sujet.
- **Wording « immuable » `result.py:3`** : à embarquer dans le **prochain bump
  naturel** de `bim-audit-engine` — on ne crée pas un bump pour un commentaire.

## 5. Ordre d'exécution consolidé

1. Hygiène §1 : 2 PRs docs-only (instruction A1 pendante ; piste de décision
   A1) → merges → tag d'archive → deletes (§1.4).
2. **Release v0.7.0** (§2).
3. PR docs-only `scope-field-path.md` amendée → gel CTO → émission + verrou.
4. Dette uv overrides (cross-repo, PR dédiée) au fil de l'eau ; wording
   `result.py` au prochain bump engine.
