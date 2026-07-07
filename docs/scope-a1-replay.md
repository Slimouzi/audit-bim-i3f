# Scope (gelé après revue CTO) — industrialisation du replay A1

Transformer la procédure A1 manuelle (`prepare → review → apply` de BCF / Smart
Views) en **workflow répétable, testé et sûr**, symétrique de l'acceptation AVP.
Instruction d'entrée : `docs/instruct-a1-replay-industrialisation.md`. Même
discipline que les scopes précédents : **décisions figées avant tout code**.

**Références (ancrage sur pièces)** :
- protocole manuel prouvé : `docs/validation-a1-bim-publication-v0.1.0.md` ;
- gardes existantes : `actions/plans.py` (`PlanIntegrityError`,
  `PlanTargetMismatchError`, `validate_target`, sceau `_sealed_sha256`),
  `mcp/tools_actions.py` (`refused_without_confirm`) ;
- pattern à imiter : `scripts/avp_acceptance/run_acceptance.py` +
  `tests/unit/test_avp_pack_acceptance.py` / `test_avp_acceptance_runner.py` ;
- goldens : `tests/unit/golden/bcf_payloads.json`, `smartview_payloads.json`.

## 0. Décisions figées (revue CTO)

- **Périmètre** : un runner `scripts/a1_replay/run_replay.py` + des helpers purs
  testables + tests CI hors-ligne. **Aucun nouveau tool MCP** ; réutilisation des
  chemins Python `prepare_*` / `apply_*`. **Aucune** modification de
  `bim-publication` ni des builders.
- **Voie d'écriture** : uniquement sur le **modèle de validation jetable** désigné
  par une variable d'environnement dédiée. Toute autre cible → refus **avant**
  tout `apply`.
- **Pas de release** tant que le replay réel n'a pas prouvé **PASS en dry-run ET
  en write**.
- **Rappel** : la dette **(c) CI bim-core est DÉJÀ faite** (`Slimouzi/bim-core#2`,
  green) — l'étape « CI bim-core d'abord » de l'ordre recommandé est **close**.

## 1. Séquence imposée au runner (gelée)

`scripts/a1_replay/run_replay.py <out_dir_hors_repo> [--write]` :

1. **Cible explicite** depuis l'environnement + **contrôle d'identité** (nom de
   modèle attendu doit matcher, sinon refus) — équivalent
   `set_active_model → verify_active_model`.
2. **Garde cible jetable** (helper pur `assert_write_target`, esprit
   `_assert_outside_repo`) : l'écriture n'est autorisée **que** sur le modèle
   `REPLAY_WRITE_MODEL_ID`. Toute autre cible → `SystemExit` avant tout `apply`.
3. **Audit réel** — catalogue CCH complet (réutiliser `assert_catalog_usable`).
4. **Préparation** — plans **scellés** BCF + Smart Views (filtre `error_types`
   figé, cf. §4 décision C), **aucune écriture**.
5. **Revue automatique** — helper pur `inspect_plan` (partagé runner ↔ tests) :
   `n_items > 0`, `risks == []`, `plan.target` == cible effective, **préfixe**
   des objets conforme (`REPLAY-BIM-PUBLICATION-YYYYMMDD — `, date injectée).
6. **Garde-fou négatif rejoué** — `apply(confirm=False)` → `refused: true` exigé.
7. **Apply** `confirm=True` **uniquement** en `--write` ; par défaut **dry-run**
   (s'arrête après 5–6 ; PASS possible sans écrire = mode planifiable).
8. **Vérification post-apply par l'API** (`--write`) — relire topics BCF / Smart
   Views créés : **compte + préfixe + cible**. C'est l'étape qui ramène le
   hand-off 5b (vérif visuelle) d'obligatoire à **contrôle périodique**.
9. **Journal** — entrées `audit_trail` présentes, `succeeded/failed` conformes.
10. **Verdict** `PASS`/`FAIL`, code 0/1 ; stdout = compteurs / booléens / verdict,
    **aucune donnée client** (politique identique à l'acceptation AVP).

## 2. Gardes testées hors réseau (CI, helpers purs)

| Garde | Attendu |
|---|---|
| `apply` sans `confirm` | refus (`refused_without_confirm`) |
| plan altéré (sceau) | `PlanIntegrityError` refusé |
| cible du plan ≠ cible effective | `PlanTargetMismatchError` refusé |
| cible ≠ modèle jetable autorisé | refus du runner (`assert_write_target`) |
| revue : plan 0 item / avec `risks` / mauvais préfixe | `inspect_plan(...).ok == False` |

`inspect_plan` s'appuie sur les **goldens** existants (payloads BCF/SmartViews)
pour un cas positif déterministe.

## 3. Contrat `inspect_plan` (helper pur, partagé)

`inspect_plan(plan, *, effective_target, expected_prefix, min_items=1) -> dict`
renvoie **compteurs + booléens + `ok`** (jamais de contenu client) :
`n_items`, `has_risks`, `target_matches`, `prefix_ok`, `ok`. Seuils identiques
côté runner et tests (leçon acceptation AVP : un seul helper de gate).

## 4. Décisions à figer (recommandations — à trancher en revue)

**A. Nettoyage des objets créés.**
`bimdata-write` n'expose **aucune** méthode de suppression et l'instruction
interdit de toucher `bim-publication`/builders. **Recommandation v1** :
**convention de préfixe daté** (`REPLAY-BIM-PUBLICATION-YYYYMMDD — `) +
**procédure de purge documentée** (manuelle/périodique) ; **pas d'auto-delete**.
Auto-suppression API = **suivi ultérieur borné** (nécessiterait une méthode
`delete_*` dans `bimdata-write` — hors scope v1).

> **Résolution (décision CTO, post-scope).** Le « suivi ultérieur borné » a été
> réalisé : `bimdata-write v0.1.1` ajoute `delete_bcf_topic` / `delete_smart_view`
> (transport `DELETE` authentifié, aucune logique métier ; `bim-publication`
> intouché). Le runner **purge désormais automatiquement** les objets qu'il crée
> après les avoir prouvés (create → verify 3 niveaux → purge → re-lecture `0`),
> pour un `--write` **déterministe en un seul run**. La sélection reste **bornée
> au préfixe daté de CE run** (helper pur `select_purge_guids`). `--keep` conserve
> les objets pour l'**inspection visuelle périodique 5b**. La procédure de purge
> manuelle du README reste le **repli** si la purge auto échoue.

**B. Fréquence.**
**Recommandation** : **dry-run planifiable** (read-only, aucune écriture, PASS
prouvable — candidat CI-cron sur le vrai modèle) ; **`--write` manuel/à la
demande uniquement** (un humain déclenche la publication réelle sur le modèle
jetable). Pas de write automatisé en v1.

**C. Compteur attendu déterministe.**
Le nombre d'items dépend de la maquette. **Recommandation** : **figer la cible** =
modèle jetable **Dieppe 1674450** (celui du replay A1 prouvé) **+ filtre figé**
`error_types=[naming_invalid_format]`, `include_overview=false` → attendu
**déterministe = 1 topic BCF + 1 Smart View** (exactement ce qu'a produit le
replay A1). Le runner asserte le compte exact ; toute dérive = **signal**
(maquette modifiée ou régression), pas un PASS silencieux.

## 5. Critères d'acceptation du jalon

1. CI hors-ligne verte (les 5 gardes + revue de plan, helpers purs partagés).
2. Replay réel **dry-run PASS** puis **write PASS** sur le modèle jetable, avec
   doc de validation versionné (**identifiant + agrégats seulement**).
3. Les **4 refus** (confirm / intégrité / cible plan / cible jetable) prouvés par
   tests.
4. Suite complète verte, ruff clean, **aucune donnée client versionnée**.

## 6. Non-buts

- Aucun nouveau tool MCP ; aucune modification de `bim-publication`/builders ;
- aucune écriture hors du modèle jetable ;
- pas de release tant que dry-run **et** write ne sont pas PASS sur le réel ;
- pas de généralisation de la consommation `field_path` ici (chantier séparé,
  au fil de l'eau).

## 7. Ordre d'exécution (post-gel)

Doc de scope gelé (ce document, trancher A/B/C) → **implémentation A1** (CI
hors-ligne : `assert_write_target` + `inspect_plan` + les 4 refus ; puis runner
réel) → validation réelle dry-run puis write → `field_path` non-zone au fil de
l'eau. *(Dette (c) CI bim-core déjà faite — pas dans le chemin.)*
