# Validation — acceptation du pack AVP (v0.6.0)

Preuve que le pack de livrables AVP I3F est **accepté sur une vraie maquette
BIMData** : les **5 annexes xlsx** sont non vides et exactes, toutes habillées de
la **charte BIMData**. Read-only (extraction seule ; aucune écriture ni
publication BIMData).

**Politique de données** : aucun **fichier brut ni livrable client** n'est
versionné — le pack complet (xlsx/docx) reste **hors du dépôt**. Ce document ne
consigne qu'un **identifiant de maquette et des agrégats approuvés** (nom IFC de la
maquette de référence I3F + compteurs/conformités), à des fins de traçabilité de la
validation. La sortie **stdout** du runner, elle, ne porte **aucun** identifiant
(phase / compteurs / booléens / verdict uniquement).

## Deux niveaux d'acceptation

1. **CI hors-ligne, déterministe** — `tests/unit/test_avp_pack_acceptance.py` :
   sur un snapshot représentatif (chemin réel piloté maquette, `sources=None`),
   les 5 annexes sont non vides, la charte (wordmark `BIMDATA`, primaire
   `#2F374A`, police `Roboto`) est présente sur les 5, sans KORHUS. Exactitude
   métier de la grille de contrôle testée (séparation Name/ObjectType, matériaux)
   **jusqu'aux valeurs de cellules Excel**.
2. **Réseau réel** — `scripts/avp_acceptance/run_acceptance.py` : génère le pack
   depuis une vraie maquette et rend un verdict PASS/FAIL. Gardes testées
   (`tests/unit/test_avp_acceptance_runner.py`) : refus si document I3F absent /
   catalogue vide / sortie dans le dépôt.

## Résultat réseau réel — **PASS**

Maquette I3F réelle (`250613_MN_BAT.ifc`, projet I3F), catalogue CCH 3.6 réel
(3 documents MOA). Verdict **PASS** ; sortie (compteurs / booléens uniquement) :

| Annexe | Lignes | Charte |
|---|---|---|
| **Contrôle** | **4** (points de contrôle réels) | ✅ |
| SHAB | 316 | ✅ |
| Zones/Espaces | 340 | ✅ |
| Enveloppe | 484 | ✅ |
| Menuiseries | 465 | ✅ |

Grille de contrôle (valeurs vérifiées) :

| Point de contrôle | Total | Conformes | Non conformes |
|---|---|---|---|
| Zones Nommage | 24 | 24 | 0 |
| Zones ObjectType | 24 | 24 | 0 |
| Pièces Nommage | 316 | 0 | 316 |
| ARC absence de matériau | 10 549 | 8 179 | 2 370 |

`Contrôle = 4` = points de contrôle réels sous la grille (compteur propre
`_count_controle_rows`, hors entête/légende/`NOT_AVAILABLE`). Les contrôles
« Zones Nommage » et « Zones ObjectType » sont comptés **indépendamment** ; le
contrôle matériau lit `material_list` (forme BIMData) et distingue conformes
(8 179) et non conformes (2 370).

## Dette connue (non bloquante)

La classification d'un finding de nommage de zone en `Name` vs `ObjectType`
repose partiellement sur le **texte** du finding (`recommended_action` /
`expected`) faute de champ structuré. À terme, exposer un champ **`control_id`**
ou **`field_path`** sur `Finding` pour une classification robuste sans heuristique
textuelle. Suivi séparément ; ne bloque pas v0.6.0.
