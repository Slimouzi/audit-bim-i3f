# Validation — acceptation du rapport Word AVP (post-v0.6.0)

Preuve d'acceptation du **6ᵉ livrable** du pack AVP — le rapport Word
(`… Rapport analyse BIM.docx`). **Postérieure au tag `v0.6.0`** : ce contrôle et le
bloc `word_report` du runner ne figurent pas dans `v0.6.0` (voir `CHANGELOG`
[Unreleased]). Read-only.

**Politique de données** (identique à `docs/validation-avp-pack-0.6.0.md`) : aucun
**fichier brut ni livrable client** n'est versionné — **uniquement un identifiant et
des agrégats approuvés** figurent ici. La sortie stdout du runner ne porte **aucun**
identifiant.

## Critères (helper unique `inspect_word_report`)

Un **seul** helper porte les critères et les seuils, **partagé** entre le runner
réseau (`scripts/avp_acceptance/run_acceptance.py`) et les tests
(`tests/unit/test_avp_pack_acceptance.py` cas positif,
`tests/unit/test_avp_acceptance_runner.py` cas négatifs) :

- **contenu non vide** : ≥ 10 paragraphes **et** ≥ 10 cellules **significatives**
  (non vides et distinctes de `NOT_AVAILABLE`) ;
- **sections 1 à 9** présentes ;
- **métadonnées** : le **vrai** nom de projet BIMData présent dans le document
  (le bouchon `ACCEPTANCE` ne satisfait **jamais** le contrôle) **et** la phase ;
- **charte BIMData** (wordmark `BIMDATA`, primaire `#2F374A`, police `Roboto`),
  **sans** KORHUS.

## Résultat réseau réel — **PASS**

Maquette I3F réelle (`250613_MN_BAT.ifc`), phase AVP. Bloc `word_report` (compteurs
/ booléens uniquement) :

| Champ | Valeur |
|---|---|
| `n_paragraphs` | 25 (≥ 10 ✅) |
| `n_significant_cells` | 46 (≥ 10 ✅, hors `NOT_AVAILABLE`) |
| `sections_present` | 1 … 9 (`sections_ok` ✅) |
| `metadata_present` | ✅ (vrai nom projet + phase) |
| charte (`wordmark`/`primary`/`font`) | ✅ / ✅ / ✅ |
| `no_korhus` | ✅ |
| `ok` | **true** |

Le code de sortie 0 du runner exige désormais **les 5 annexes xlsx ET le rapport
Word**.

## Tests négatifs (helper, sans réseau)

`test_avp_acceptance_runner.py` prouve que le helper **rejette** : un DOCX 1×1
brandé (contenu maigre), des cellules uniquement `NOT_AVAILABLE`, une section
obligatoire manquante, et un nom de projet absent ou égal au bouchon.
