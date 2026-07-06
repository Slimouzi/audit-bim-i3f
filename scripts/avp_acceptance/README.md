# Acceptation réelle du pack AVP (`avp_acceptance`)

Complément **réseau réel** du test CI hors-ligne
`tests/unit/test_avp_pack_acceptance.py` : génère le pack AVP depuis une **vraie
maquette BIMData** et vérifie que **les 5 annexes** sont non vides et habillées de
la **charte BIMData**.

## ⚠️ Données client — ne jamais versionner

`run_acceptance.py` génère un pack (xlsx/docx) qui contient des **données client**.
Il **refuse** d'écrire dans le dépôt (garde `_assert_outside_repo`) → passe un
dossier de sortie **hors du repo** (ex. `/tmp/avp-acceptance`). Le `.gitignore`
local ignore aussi `*.xlsx`/`*.docx`/`*.json` par précaution.

La sortie **stdout** est sûre à archiver : uniquement des **compteurs** (lignes
métier par annexe), des **booléens** de charte et un **verdict** — aucune donnée
client.

## Read-only

Extraction du modèle uniquement ; **aucune écriture BIMData**, aucune publication
(pas de BCF / Smart Views / classifications).

## Usage

```bash
# Cible + auth via l'environnement (.env) : BIMDATA_API_KEY, BIMDATA_CLOUD_ID,
# BIMDATA_PROJECT_ID, BIMDATA_MODEL_ID, BIMDATA_BASE_URL…
python scripts/avp_acceptance/run_acceptance.py /tmp/avp-acceptance
```

Sortie (exemple de forme, sans donnée client) :

```json
{
  "phase": "AVP",
  "annexes": {
    "Contrôle":      {"rows": 4,   "non_empty": true, "wordmark": true, "primary": true, "font": true, "no_korhus": true},
    "SHAB":          {"rows": 316, "non_empty": true, ...},
    "Zones/Espaces": {"rows": 340, "non_empty": true, ...},
    "Enveloppe":     {"rows": 484, "non_empty": true, ...},
    "Menuiseries":   {"rows": 465, "non_empty": true, ...}
  },
  "word_report": {"n_paragraphs": 25, "n_table_cells": 56, "non_empty": true, "metadata_present": true, "wordmark": true, "primary": true, "font": true, "no_korhus": true},
  "verdict": "PASS"
}
```

Le **rapport Word** (`analyse BIM AVP.docx`) est également accepté (helper unique
`inspect_word_report`, mêmes seuils que les tests) : contenu non vide (**≥ 10
paragraphes ET ≥ 10 cellules significatives** hors `NOT_AVAILABLE`), **sections 1 à
9**, charte BIMData, métadonnées projet/phase présentes (`metadata_present` —
booléen ; le **vrai** nom de projet est comparé au texte du doc mais **pas** émis,
et le bouchon `ACCEPTANCE` ne satisfait **jamais** le contrôle), sans KORHUS.

**Code de sortie 0** si `PASS`, c.-à-d. **les 5 annexes xlsx non vides + charte, ET
le rapport Word conforme** ; 1 sinon.

`Contrôle` est mesuré par un **compteur propre** (`_count_controle_rows`) : il ne
compte que les **points de contrôle** sous la grille (hors bandeau / entête projet
/ légende / titres / `NOT_AVAILABLE`) — d'où `rows: 4` sur la maquette de référence
(Zones Nommage, Pièces Nommage, ARC matériau, Zones ObjectType). Les 4 autres
annexes utilisent le compteur générique de lignes métier.
