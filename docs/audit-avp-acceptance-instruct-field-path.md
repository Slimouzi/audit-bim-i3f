# Audit — clôture du jalon d'acceptation AVP & instruction `field_path`

Audit indépendant de la clôture annoncée du **jalon d'acceptation AVP**
(Excel + Word), réalisé sur `HEAD = 36cad4e` (#72, qui intègre `942fcac`),
suivi de l'**instruction** — depuis **exécutée** (`bim-core-v0.1.1` + PR #73,
voir §3) — du champ structuré `field_path` sur `Finding` (fiabilisation de la
grille de contrôle), et du **registre de dette** ouvert (§4).

**Politique de données** (identique aux docs de validation) : aucun fichier brut
ni livrable client — uniquement des chemins de code, compteurs et booléens.

## 1. Verdict d'audit : jalon confirmé fermé

Chaque affirmation de clôture a été vérifiée contre le dépôt :

| Affirmation | Preuve vérifiée | Verdict |
|---|---|---|
| P2 — sections vérifiées par intitulé métier, plus seulement par numéro | Table `WORD_SECTION_TITLES` (9 intitulés, `run_acceptance.py`) ; `sections_ok` exige numéro **ET** mot-clé métier pour chaque section 1–9 | ✅ |
| P2 — test négatif « numéros présents + intitulés faux → refus » | `tests/unit/test_avp_acceptance_runner.py::test_word_reject_numbers_present_wrong_titles` (`sections_ok is False`) | ✅ |
| Cohérence table ↔ générateur | Les 9 titres émis par `audit_bim/reporting/avp_i3f.py` (« 1. Données d'entrée » … « 9. Annexes — statistiques de conformité ») contiennent chacun le mot-clé de la table | ✅ |
| P3 — formulation confidentialité validée | « aucun **fichier brut ni livrable client** … **uniquement un identifiant et des agrégats approuvés** » présente dans `docs/validation-avp-word-post-0.6.0.md` et `docs/validation-avp-pack-0.6.0.md` | ✅ |
| Helpers de gate purs et partagés | `inspect_word_report`, `assert_catalog_usable`, `_assert_outside_repo` (runner) ; `_count_controle_rows` (reporting, importé par le runner) — tous couverts par les tests hors réseau | ✅ |
| Suite verte, ruff clean | Rejoué localement : **1065 passed, 5 skipped** (extras `[ocr]` non installés), exit 0 ; `ruff check` + `ruff format --check` sans écart (193 fichiers) | ✅ |
| Aucune donnée client versionnée | Docs de validation = identifiant + agrégats uniquement ; garde `_assert_outside_repo` active et testée | ✅ |
| CHANGELOG `[Unreleased]`, pas de nouvelle release | Bloc `[Unreleased]` porte l'acceptation Word ; `v0.6.0` inchangé | ✅ |

Note de comptage : la clôture annonçait « suite 1074 » ; localement **1069
tests collectés** sans les extras `[ocr]` (les modules OCR skippés). Écart
d'environnement, pas de régression — les 1065 exécutés passent tous.

## 2. Écart corrigé par cet audit

Un seul écart réel entre l'annonce et le code :

- **Match des intitulés « insensible casse/accents »** : le commentaire (et la
  clôture) promettaient l'insensibilité aux **accents**, mais le code
  n'appliquait que `casefold()` (casse seule). Non bloquant en pratique — le
  générateur émet les mêmes accents que la table — mais le gate promettait
  plus qu'il ne tenait. **Corrigé** : normalisation NFKD + suppression des
  diacritiques (`_norm_title`), avec test positif
  `test_word_accepts_unaccented_titles` (titres « DONNEES D'ENTREE »,
  « ECARTS »… → `sections_ok:true`).

## 3. Instruction — champ structuré `field_path` sur `Finding` — **EXÉCUTÉE**

> **Clôture.** L'instruction ci-dessous a été exécutée intégralement :
> **Étape A** = `bim-core-v0.1.1` (commit `d7f776a`, dépôt `Slimouzi/bim-core`) ;
> **Étapes B + C** = PR **#73** (mergée sur master, `562684f`), auditée sur
> pièces : pin bumpé partout (sources uv, préinstalls CI/release, README),
> émission sur les 4 sites zone, consommation prioritaire dans
> `_zone_finding_kind` (heuristique en repli), 8 verrous dans
> `tests/unit/test_zone_field_path.py`, goldens sans `field_path`, CI verte.
> Le texte prescriptif est conservé tel quel comme référence de conception.

**Objectif** : supprimer la fragilité de classification Name/ObjectType de la
grille de contrôle. `_zone_finding_kind` (`audit_bim/reporting/avp_i3f.py`)
discriminait les deux contrôles de zone par **heuristique de wording**
(`"objecttype"` cherché dans `recommended_action`/`expected`) : un simple
changement de formulation des findings dans `audit_bim/audit/rules/naming.py`
aurait faussé **silencieusement** les comptes de conformité de la grille.

**Contrainte inter-dépôts** : `Finding` vit dans **`bim-core`** (dépendance Git
taguée, dépôt `Slimouzi/bim-core`) — la première étape se joue donc hors de ce
dépôt. `bim-core` étant générique, on n'y introduit **pas** de `control_id`
I3F : un seul champ **neutre** suffit.

### Étape A — `bim-core` v0.1.1 (dépôt `Slimouzi/bim-core`) — ✅ faite

- Ajouter à `Finding` un champ optionnel rétro-compatible :
  `field_path: str | None = None` — chemin structuré de l'attribut contrôlé,
  format `"<ClasseIfc>.<Attribut>"` (ex. `"IfcZone.Name"`,
  `"IfcZone.ObjectType"`, `"IfcSpace.LongName"`).
- Défaut `None` ⇒ aucun consommateur existant ne casse ; sérialisation JSON
  inchangée pour les findings historiques.
- Tag `bim-core-v0.1.1` (même playbook que les extractions précédentes ;
  la décision #66 « pas de package sans 2ᵉ consommateur » n'est pas concernée :
  `bim-core` existe déjà et c'est le foyer désigné des contrats communs).

### Étape B — ce dépôt (adoption) — ✅ faite (PR #73)

1. Bump du pin : `bim-core>=0.1.0,<0.2` conservé, tag `bim-core-v0.1.1` dans
   `[tool.uv.sources]` + préinstalls CI/release + README + `uv.lock`.
2. **Émission** : `field_path` renseigné sur les findings de nommage de zone
   dans `audit_bim/audit/rules/naming.py` (4 sites : Name manquant / format
   invalide → `"IfcZone.Name"` ; ObjectType manquant / hors liste →
   `"IfcZone.ObjectType"`), puis progressivement sur les autres règles.
3. **Consommation** : `_zone_finding_kind` lit `f.field_path` en **premier**
   (source de vérité) et ne garde l'heuristique de wording qu'en **repli**
   pour les findings sérialisés antérieurs.

Contrainte rencontrée : uv honore les `[tool.uv.sources]` des git-deps — les
5 packages first-party transitifs épinglant encore `bim-core-v0.1.0`, le bump
isolé créait un conflit de résolution. Fix retenu : `[tool.uv]
override-dependencies` force le graphe sur `v0.1.1` (sûr, v0.1.1 strictement
additif) — voir registre de dette (a).

### Étape C — verrouillage par les tests — ✅ faite (`test_zone_field_path.py`, 8 tests)

- Test d'émission : tout finding `NAMING_ZONE` produit par la vraie règle porte
  un `field_path` non nul (empêche la régression « nouveau finding sans champ »).
- Test anti-wording : un libellé trompeur ne change **plus** la classification
  Name/ObjectType — `field_path` gagne dans les deux sens.
- Repli : un finding sans `field_path` (sérialisé avant le champ) est classé à
  l'identique par l'heuristique ; goldens de publication inchangés
  (`field_path` absent des goldens, parité verte).

## 4. Registre de dette (ouvert)

- **(a) Retirer l'override uv** : bumper le pin `bim-core` des 5 packages
  transitifs (`bimdata-read`, `bimdata-write`, `bim-query`, `bim-publication`,
  `bim-audit-engine`) sur `bim-core-v0.1.1` **à leur prochaine release
  naturelle** (pas de train de re-tags dédié), puis supprimer
  `override-dependencies` du `pyproject.toml`. Tant que l'override existe, il
  masquerait un conflit *légitime* sur bim-core : chaque bump de bim-core doit
  re-vérifier la compatibilité du graphe.
- **(b) Wording « immuable »** de `bim_audit_engine/result.py:3` (dépôt
  `Slimouzi/bim-audit-engine`) : le docstring annonce un « agrégat immuable »
  alors que la dataclass n'est pas `frozen` et que `findings` est une liste
  mutable. Au choix : geler (`frozen=True` + tuple) ou corriger le docstring —
  à trancher au prochain bump `bim-audit-engine`, sans jalon dédié.
- **(c) CI sur `bim-core`** : le package de contrats (consommé par les 7
  dépôts) n'a **aucune CI**, contrairement aux 6 autres first-party. Ajouter le
  workflow minimal (ruff + pytest + build) **avant le prochain bump** — un tag
  cassé casserait les 7 pipelines d'un coup.

### Hors périmètre

- Hand-off 5b (vérification visuelle viewer des objets
  `REPLAY-BIM-PUBLICATION`) : action humaine, inchangée.
