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
  "model": "…",
  "phase": "AVP",
  "annexes": {
    "Contrôle":      {"rows": 7,  "non_empty": true, "wordmark": true, "primary": true, "font": true, "no_korhus": true},
    "SHAB":          {"rows": 316, "non_empty": true, ...},
    "Zones/Espaces": {"rows": 24,  "non_empty": true, ...},
    "Enveloppe":     {"rows": 12,  "non_empty": true, ...},
    "Menuiseries":   {"rows": 464, "non_empty": true, ...}
  },
  "verdict": "PASS"
}
```

Code de sortie 0 si `PASS` (5 annexes non vides + charte sur les 5), 1 sinon.
