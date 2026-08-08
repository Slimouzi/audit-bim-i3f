# Scope — package `bimdata-write`

> **Document historique.** Rédigé quand la distribution s'appelait
> `audit-bim-i3f` ; elle se nomme **`audit-bim-mcp`** depuis la 0.11.0
> (2026-08-08). Les noms cités ci-dessous n'ont **pas** été réécrits : ce
> document est une trace de décision, pas une consigne courante.

Document d'architecture **figé avant tout code**. Il cartographie la surface
**réelle d'écriture** BIMData d'`audit-bim-i3f`, fixe la frontière du futur
package `bimdata-write`, l'ordre des PR et les critères de parité.

**Cette PR ne modifie aucun code applicatif** — inventaire et décision seulement.

Objectif : sortir le **transport d'écriture** BIMData dans un package pur, où
chaque écriture est une **méthode nommée, testable et auditée** — plus aucun
appel `_post` brut dispersé dans le code métier.

## 1. Surface d'écriture réelle (inventaire)

Aujourd'hui, les écritures BIMData passent par `BIMDataClient._post` (transport
POST générique), appelé soit via la méthode nommée `create_bcf_full_topic`, soit
**directement en `_post` brut** depuis le code métier.

| # | Action | Endpoint | Appel actuel | Payload |
|---|---|---|---|---|
| 1 | Créer une classification | `POST /cloud/{c}/project/{p}/classification` | **`_post` brut** — `classifier/applier.py:140` | `{name, notation, title}` → `{id}` |
| 2 | Affecter classifications aux éléments (bulk) | `POST /cloud/{c}/project/{p}/model/{m}/classification-element` | **`_post` brut** — `classifier/applier.py:192` | items `{classification, element}` |
| 3 | Écrire un property set sur un élément | `POST /cloud/{c}/project/{p}/model/{m}/element/{uuid}/propertyset` | **`_post` brut** — `doe/enricher.py:214`, `actions/doe_planner.py:274` | pset `{name, properties[…]}` |
| 4 | Créer un BCF Full-Topic (BCF **et** Smart Views) | `POST /bcf/2.1/projects/{p}/full-topic` | **méthode nommée** `create_bcf_full_topic` — `extraction/client.py:96` | FullTopic ( + `format: "bimdata-smartview"` pour le panneau Smart Views) |

Lecture couplée aux écritures (reste en lecture, via `bimdata-read`) :
`GET /cloud/{c}/project/{p}/classification` (`list_project_classifications`,
`applier.py:42`) et `get_model()` (validations). ⇒ le client d'écriture doit
avoir accès à la lecture.

Consommateurs d'écriture (code métier, restent en audit-bim) :
`classifier/applier.py`, `doe/enricher.py`, `bcf/builder.py`,
`smartview/builder.py`, `actions/{bcf,smartview,classification,doe}_planner.py`.

## 2. Garde-fous (restent dans `audit-bim-i3f`)

Ils encadrent l'**intention** et la **sécurité** — hors transport, donc **non
extraits** :

- **`WritePlan`** + `save_plan`/`load_plan` + checksum SHA-256 + `requires_confirm`
  (`domain/write_plan.py`, `actions/plans.py`) — plan scellé, revue avant apply.
- **`dry_run`** — présent dans `bcf/builder.py:273`, `smartview/builder.py`,
  `classifier/applier.py`, `doe/enricher.py`, `actions/doe_planner.py` : décision
  métier de simuler vs écrire.
- **`ensure_writes_allowed`** (`mcp/security.py`) — garde MCP sur tous les
  `apply_*` (réseau, `AUDIT_BIM_ALLOW_WRITES`).
- **Journal d'écritures** — `WriteJournal` / `get_journal` / `WriteJournalEntry`
  (`security/write_journal.py`).
- **Sandbox chemins** — `safe_paths` (inputs/outputs).

## 3. Décision d'architecture

**Package d'abord, MCP ensuite.** On extrait `bimdata-write` en package pur et
testé ; on ne décidera d'un **MCP BIMData Write autonome** qu'une fois la
frontière du package stable.

Composition des clients (recommandée) :

```
bim-core (contrats)
   ▲
bimdata-read  : BIMDataReadClient  (lecture, config-agnostic)
   ▲
bimdata-write : BIMDataWriteClient(BIMDataReadClient)  (+ écritures nommées)
   ▲
audit-bim-i3f : BIMDataClient = façade config.* (import historique inchangé)
```

`BIMDataWriteClient` **hérite** de `BIMDataReadClient` (les écritures ont besoin
de lecture : list classifications, get_model). `bimdata-write` dépend donc de
`bimdata-read` + `bim-core`. La façade `audit_bim.extraction.client.BIMDataClient`
délègue les écritures au package et conserve le fallback `config.*`.

## 4. Frontière

### `bimdata-write` contient

- **Client d'écriture config-agnostic** `BIMDataWriteClient(BIMDataReadClient)`
  (base_url + auth en paramètres, comme `bimdata-read`).
- **Transport authentifié POST/PATCH/DELETE** (`_post` interne + gestion 401/403
  homogène via `BIMDataAuthError`, réutilisé de `bimdata-read`).
- **Méthodes explicites** remplaçant les `_post` bruts :
  | Méthode nommée | Remplace | Endpoint |
  |---|---|---|
  | `create_classification(name, notation, title) -> id` | `applier.py:140` | `POST …/classification` |
  | `assign_classification_elements(items) -> resp` | `applier.py:192` | `POST …/classification-element` |
  | `write_element_propertyset(element_uuid, payload)` | `enricher.py:214`, `doe_planner.py:274` | `POST …/element/{uuid}/propertyset` |
  | `create_bcf_full_topic(payload)` | (déjà nommée, à déplacer) | `POST /bcf/2.1/projects/{p}/full-topic` |
- **Erreurs auth/HTTP homogènes** (réutilise `BIMDataAuthError`).
- Éventuellement des **helpers bas niveau** BCF / Smart View **s'ils sont
  génériques** (ex. composition de viewpoint/coloring) — à n'extraire que si
  réutilisables hors I3F ; sinon rester côté builders.

### `audit-bim-i3f` garde

- Logique métier I3F, `planners`/`actions`, builders `bcf/`/`smartview/`.
- `WritePlan` et validations d'intention (checksum, `requires_confirm`).
- `dry_run`, journal, sandbox, `ensure_writes_allowed`.
- Wording utilisateur et décisions MCP (`prepare_*`/`apply_*`, aliases).

## 5. Ordre PR officiel

0. **PR scope** — `docs/scope-bimdata-write.md` (cette PR). Aucun code.
1. **`bimdata-write` package pur + testé** : `BIMDataWriteClient` + méthodes
   nommées, dépend de `bimdata-read` + `bim-core`. Tests offline (transport
   mocké) : chaque méthode construit la bonne URL + payload.
2. **Tag** `bimdata-write-v0.1.0` (repo public, comme bim-core/bimdata-read).
3. **PR adoption** — `pyproject` + `[tool.uv.sources]` + `uv.lock` + CI/release
   (install `bimdata-write@tag`, `--no-emit-package`), infra only.
4. **PR shims** — la façade `audit_bim.extraction.client.BIMDataClient` garde
   l'import historique mais **délègue les écritures** au package ; les 4 appels
   `_post` bruts (`applier` ×2, `enricher`, `doe_planner`) passent aux **méthodes
   nommées**. `normalizer.py` et les garde-fous inchangés.
5. **Ensuite seulement** : décider si un **MCP BIMData Write** autonome est
   nécessaire.

## 6. Critère de parité (gate)

- **Aucun endpoint d'écriture appelé via `_post` brut** après extraction : les 4
  sites (`applier.py:140/192`, `enricher.py:214`, `doe_planner.py:274`) utilisent
  des **méthodes nommées**. Grep de garde en CI : `client._post(` interdit hors
  du package.
- Chaque écriture = méthode **nommée, testable** (URL + payload vérifiés en test
  offline) et **auditée** (journal inchangé).
- **Parité tests** : mêmes unit + integration verts ; test d'identité (anciens
  chemins → objets `bimdata-write`).
- **Aucun changement d'outil MCP** ni de comportement `dry_run`/`confirm`.
- CI verte depuis install propre (`bimdata-write@tag` public résolu).

## 7. Hors scope

- La création d'un MCP Write autonome (décision post-package).
- Toute nouvelle logique métier ou changement d'intention/dry_run/journal.
- Les helpers spécifiques I3F (nommage BCF, sélection enveloppe…) restent en
  audit-bim.
