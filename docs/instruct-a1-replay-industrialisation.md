# Instruction — industrialisation du replay A1 (écriture BCF / Smart Views)

Cadrage du **prochain jalon produit** arrêté par le CTO : transformer la
procédure A1 manuelle (`prepare → review → apply`) en **workflow répétable,
testé et sûr**, symétrique de l'acceptation AVP. Chantier secondaire retenu
avec : **extension de `field_path` aux règles non-zone**. Ce document est
l'instruction d'entrée du doc de scope gelé (même discipline que
`docs/scope-bim-publication.md` : décisions figées avant tout code).

**Références** : protocole manuel prouvé dans
`docs/validation-a1-bim-publication-v0.1.0.md` ; pattern d'acceptation à
imiter dans `tests/unit/test_avp_pack_acceptance.py` +
`scripts/avp_acceptance/run_acceptance.py`.

## 1. Jalon principal — replay A1 industrialisé

### Objectif

Un **runner** `scripts/a1_replay/run_replay.py` rejoue le protocole A1 de bout
en bout avec un verdict machine (code 0 = PASS), au lieu d'une séquence MCP
manuelle. Deux niveaux, comme l'acceptation AVP :

- **CI hors-ligne** : helpers purs testés sans réseau (revue de plan, gardes)
  — s'appuyer sur les goldens existants (`tests/unit/golden/bcf_payloads.json`,
  `smartview_payloads.json`) ;
- **runner réseau réel** : replay sur le **modèle de validation jetable**.

### Séquence imposée au runner

1. **Cible explicite** depuis l'environnement + contrôle d'identité
   (équivalent `set_active_model` → `verify_active_model` : le nom de modèle
   attendu doit matcher, sinon refus).
2. **Garde cible jetable** : l'écriture n'est autorisée **que** sur le modèle
   de validation désigné par une variable d'environnement dédiée (ex.
   `REPLAY_WRITE_MODEL_ID`). Toute autre cible → `SystemExit` **avant** tout
   `apply`. Helper pur testable (même esprit que `_assert_outside_repo`).
3. **Audit réel** (catalogue CCH complet — réutiliser `assert_catalog_usable`).
4. **Préparation** : plans scellés BCF + Smart Views (filtre `error_types`
   paramétrable), **aucune écriture**.
5. **Revue automatique** (helper pur `inspect_plan`, partagé runner ↔ tests) :
   `n_items > 0`, `risks == []`, `plan.target` == cible effective, préfixe
   des objets conforme (`REPLAY-BIM-PUBLICATION-YYYYMMDD — `, date injectée).
6. **Garde-fou négatif rejoué à chaque run** : `apply(confirm=False)` →
   `refused: true` exigé (le refus fait partie du contrat, il se re-prouve).
7. **Apply** `confirm=True` **uniquement** en mode `--write` explicite ;
   par défaut le runner est **dry-run** et s'arrête après 5–6 (PASS possible
   sans écrire — c'est le mode CI-cron envisageable).
8. **Vérification post-apply par l'API** (mode `--write`) : relire les topics
   BCF / Smart Views créés et vérifier compte + préfixe + cible. C'est cette
   étape qui **réduit le hand-off 5b** (vérif visuelle humaine) à un contrôle
   périodique au lieu d'une étape obligatoire de chaque replay.
9. **Journal** : entrées `audit_trail` présentes, `succeeded/failed` conformes.
10. **Verdict** `PASS`/`FAIL`, code retour 0/1. Sortie stdout = compteurs,
    booléens, verdict — **aucune donnée client** (politique identique à
    l'acceptation AVP).

### Gardes à tester hors réseau (CI)

- `apply` sans `confirm` → refus (existant : `refused_without_confirm`) ;
- plan altéré → `PlanIntegrityError` refusé ;
- cible du plan ≠ cible effective → `PlanTargetMismatchError` refusé ;
- cible ≠ modèle jetable autorisé → refus du runner (nouveau helper) ;
- revue : plan sans item / avec risks / mauvais préfixe → `ok: False`.

### Décisions à figer dans le doc de scope (avant code)

- **Nettoyage** des objets créés : suppression API post-run si praticable,
  sinon convention préfixe + procédure de purge documentée. À trancher.
- **Fréquence** : replay à la demande vs planifié (le dry-run est planifiable
  sans risque ; le `--write` reste manuel dans un premier temps).
- **Compteur attendu** : le nombre d'items des plans dépend de la maquette
  jetable — figer la cible (maquette + filtre) pour que PASS soit déterministe.

### Non-buts

- Aucun nouveau tool MCP (réutiliser `prepare_*`/`apply_*` côté code Python,
  pas via le serveur) ; aucune modification de `bim-publication` ni des
  builders ; aucune écriture hors du modèle jetable ; pas de release tant que
  le replay réel n'a pas prouvé PASS (dry-run **et** write).

### Critères d'acceptation du jalon

1. CI hors-ligne verte (gardes + revue de plan, helpers purs partagés).
2. Replay réel **dry-run PASS** puis **write PASS** sur le modèle jetable,
   avec doc de validation versionné (identifiant + agrégats seulement).
3. Les 4 refus (confirm/intégrité/cible plan/cible jetable) prouvés par tests.
4. Suite complète verte, ruff clean, aucune donnée client versionnée.

## 2. Chantier secondaire — `field_path` sur les règles non-zone

Mécanique, au fil de l'eau (pas bloquant pour le jalon A1) :

- **Format à figer d'abord** (c'est un contrat de fait) : proposer
  `"<ClasseIfc>.<Attribut>"` pour les attributs natifs (ex. `IfcSpace.LongName`)
  et `"<ClasseIfc>.<Pset>.<Propriété>"` pour les propriétés (ex.
  `IfcWall.Pset_WallCommon.IsExternal`). Les findings **projet** sans attribut
  (ex. « ≥ 1 IfcSite attendu ») restent à `None` — liste d'exemptions
  explicite.
- **Émission** : `naming.py` (espaces, étages — les zones sont faites),
  `properties.py`, `classifications.py`, `uniqueness.py`, `spatial.py`,
  `lists.py`.
- **Consommation** : `_audit_stats` « Pièces Nommage » (aujourd'hui par thème,
  `avp_i3f.py`) peut basculer sur `field_path` ; autres agrégats quand un
  besoin réel apparaît — ne pas généraliser la consommation sans consommateur.
- **Verrou** : test générique « tout finding émis par `I3F_RULES` porte un
  `field_path` non nul, sauf exemptions listées » — la liste d'exemptions rend
  toute omission nouvelle visible en revue.

## 3. Rappels (registre de dette, inchangé)

Voir `docs/audit-avp-acceptance-instruct-field-path.md` §4 : (a) retrait de
l'override uv après bump des 5 transitifs ; (b) wording « immuable »
`bim_audit_engine/result.py` ; (c) **CI sur `bim-core` avant son prochain
bump** — à faire en premier, c'est court et ça protège les 7 pipelines.

**Ordre recommandé** : doc de scope gelé A1 (trancher nettoyage / fréquence /
compteur attendu) → dette (c) CI bim-core → implémentation A1 (CI hors-ligne
puis runner réel) → `field_path` non-zone au fil de l'eau.
