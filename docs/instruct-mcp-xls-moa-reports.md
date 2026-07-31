# Instructions CTO - Catalogue MCP des rapports XLS MOA et generation a l'identique

Date: 2026-07-31

## Objectif

Le MCP doit proposer une liste explicite de rapports XLS preparables pour une mission AVP I3F, verifier si les donnees necessaires sont disponibles dans la session courante, puis generer les fichiers au format du maitre d'ouvrage lorsque c'est possible.

Les exemples de reference sont dans `/Users/stani/code/MCP/Documents maître d'ouvrage/`:

- `260130 Tarare export Menuiseries.xlsx`
- `260130 Tarare Export Zones et Espaces.xlsx`
- `260130 Tarare Extraction surface enveloppe.xlsx`
- `260201 Tatare 0546L AVP - export SHAB maquette.xlsx`
- `260203 Tatare 0546L AVP - export plancher.xlsx`

Le repo sait deja generer un pack AVP via `generate_avp_i3f_pack`. Le mode courant doit etre maquette-first: les donnees metier integrees aux rapports viennent du snapshot IFC et des quantites extraites ou calculees via IFC OpenShell. Les fichiers MOA servent de references/templates et de contexte documentaire, pas de source autoritaire des surfaces.

## Position CTO

Ne pas presenter "generation a l'identique" comme disponible si le MCP n'a que le snapshot BIMData. Le snapshot permet de produire des rapports metier utiles avec donnees IFC/OpenShell, mais pas de reconstruire strictement les tableaux croises Excel natifs, formules et styles MOA sans mode template.

La generation a l'identique doit etre un mode separe, par exemple `mode="moa_template"`, fonde sur:

- un catalogue de rapports et de donnees requises;
- une verification de disponibilite avant generation;
- une reproduction de workbook par template Excel, pas par reconstruction visuelle approximative;
- une QA qui compare les signatures des fichiers produits aux exemples MOA.

## Rapports XLS a proposer

Le MCP doit exposer ces rapports, dans cet ordre:

| Cle | Fichier MOA de reference | Statut repo actuel | Decision |
| --- | --- | --- | --- |
| `controle_maquettes` | `260211 Tarare 0546L Contrôle Maquettes AVP.xlsx` | Genere dans le pack existant | Garder, meme s'il n'etait pas dans la liste des 5 PJ |
| `shab_maquette` | `260201 Tatare 0546L AVP - export SHAB maquette.xlsx` | Genere, mais pas a l'identique | Passer en mode template MOA |
| `zones_espaces` | `260130 Tarare Export Zones et Espaces.xlsx` | Genere, mais pas a l'identique | Passer en mode template MOA |
| `surface_enveloppe` | `260130 Tarare Extraction surface enveloppe.xlsx` | Genere, mais pas a l'identique | Passer en mode template MOA |
| `menuiseries` | `260130 Tarare export Menuiseries.xlsx` | Genere, mais pas a l'identique | Passer en mode template MOA |
| `plancher` | `260203 Tatare 0546L AVP - export plancher.xlsx` | Non gere dans le pack actuel | Ajouter au catalogue et au generateur |

## Signatures des classeurs MOA

### Menuiseries

- Onglet: `TDB 2022 05.1 - Fenêtres Ok`
- Zone utile: lignes 1 a 20, colonnes A a N
- En-tetes ligne 1:
  `Composant`, `Type`, `Matériau`, `BaseQuantities.Width`, `BaseQuantities.Height`, `Surface Natif`, `Nombre`, `Largeur`, `Hauteur`, `Surface IFC OpenShell`, `Ecart de largeur`, `Ecart de heuteur`, cellule vide, `Couleur`
- Formules:
  - `K2:K16 = IF(Hn-Dn=0,"",Hn-Dn)`
  - `L2:L16 = IF(In-En=0,"",In-En)`
  - `C17 = COUNTA(D2:D16)` avec libelle `Nombre de types de menuiseries` en B17
- Donnees obligatoires:
  - composants `IfcWindow`, `IfcWindowStandardCase`, `IfcDoor`, `IfcDoorStandardCase`;
  - type, materiau, largeur, hauteur, surface native, nombre;
  - largeur, hauteur et surface IFC OpenShell pour une reproduction metier des ecarts.
- Verdict disponibilite:
  - BIMData snapshot: suffisant pour largeur/hauteur/surface native si BaseQuantities presentes;
  - mode template MOA: requis pour les pivots/formules/styles a l'identique.

### Zones et Espaces

- Onglets: `Feuil2`, `TDB 2022 01.3 - Export Zones...`, `Feuil1`
- `Feuil2`:
  - pivot lignes 3 a 32, colonnes A a S;
  - ligne 3: `Somme de Surface Nette (Qté de Base)`, `Étiquettes de colonnes`;
  - ligne 4: `Étiquettes de lignes` puis types de pieces, puis `Total général`;
  - ligne 32: total general, total attendu dans l'exemple `2164.98`.
- `TDB 2022 01.3 - Export Zones...`:
  - table lignes 1 a 301, colonnes A a L;
  - en-tetes: `Composant`, `Nom Zone`, `Type de Zone`, `Groupes`, `Pièce (Nombre)`, `Type Pièce`, `Surface IFC OpenShell`, `Surface Nette (Qté de Base)`, `Étage`, `Surface Brute (Qté de Base)`, `Couleur`, `écarts`;
  - formules de recopie en A/B/C sur de nombreuses lignes;
  - formule d'ecart colonne L: `IF(Hn/Gn-1=0,"",Hn/Gn-1)`.
- `Feuil1`: onglet vide a conserver.
- Donnees obligatoires:
  - zones `IfcZone`, espaces `IfcSpace`, rattachements zone-espace, etages;
  - typologie zone/logement, nom/type de piece;
  - surfaces IFC OpenShell, surfaces nettes/brutes BaseQuantities.
- Verdict disponibilite:
  - BIMData snapshot: bon pour espaces, zones, etages et BaseQuantities si extraits;
  - mode template MOA: requis pour reproduire le pivot Excel strictement.

### Surface enveloppe

- Onglet: `TDB 2022 04.2 - Extraction s...`
- Zone utile: lignes 1 a 18, colonnes A a J
- En-tetes ligne 1:
  `Composant`, `Type`, `Étages`, `Archicad BQ NetSideArea`, `Surface IFC OpenShell`, `ArchiCAD Superficie des ouvertures sur face extérieure`, `IFC OpenShell Surface des Fenêtres`, `IFC OpenShell Surface des Portes`, `Nombre`, `Couleur`
- Formules et synthese:
  - `D11 = SUM(D2:D10)`
  - `E11 = SUM(E2:E10)`
  - `F11 = SUM(F2:F9)`
  - `E12 = E11/D11-1`
  - `D16 = GETPIVOTDATA("Surface Nette (Qté de Base)",[1]Feuil2!$A$3)`
  - `D17 = D11/D16`
  - ligne 18: `Seuil 3F 2026 :` avec valeur `0.9`
- Donnees obligatoires:
  - murs d'enveloppe `IfcWall` et `IfcWallStandardCase` sur layer contenant `Extérieurs périphériques`;
  - type, etage, `BaseQuantities.NetSideArea`, nombre;
  - surfaces IFC OpenShell, ouvertures exterieures, surfaces fenetres/portes IFC OpenShell;
  - SHAB issue du pivot zones/SHAB pour `GETPIVOTDATA`.
- Verdict disponibilite:
  - BIMData snapshot: partiel a bon pour murs, layers et surfaces natives;
  - mode template MOA: requis pour `GETPIVOTDATA` strict.

### SHAB maquette

- Onglets: `Feuil1`, `TDB 2022 01.3 - Export Zones...`
- `Feuil1`:
  - pivot lignes 3 a 32, colonnes A a S;
  - ligne 3: `SHAB (Qté de Base)`, `Pièces`;
  - ligne 4: `Logement` puis types de pieces, puis `Total général`;
  - ligne 32: total general, total attendu dans l'exemple `2164.98`.
- `TDB 2022 01.3 - Export Zones...`:
  - table lignes 1 a 303, colonnes A a L;
  - en-tetes: `Composant`, `Nom Zone`, `Type de Zone`, `Groupes`, `Pièce`, `Type Pièce`, `Surface IFC OpenShell`, `Surface Nette (Qté de Base)`, `Étage`, `Surface Brute (Qté de Base)`, `Couleur`, `écarts`;
  - formule d'ecart colonne L: `IF(Gn-Hn=0,"",Gn-Hn)`.
- Donnees obligatoires:
  - espaces, zones/logements, types de pieces, etages;
  - `Surface Nette (Qté de Base)` et `Surface Brute (Qté de Base)`;
  - surface IFC OpenShell pour calcul d'ecart metier.
- Verdict disponibilite:
  - BIMData snapshot: bon pour surfaces BaseQuantities et relations si elles sont extraites;
  - mode template MOA: requis pour le pivot Excel strict.

### Plancher

- Onglets: `TDB 2022 xx.2 - Dalles Ok`, `Planchers`
- `TDB 2022 xx.2 - Dalles Ok`:
  - table lignes 1 a 50, colonnes A a G;
  - en-tetes: `Composant`, `Type`, `Étage`, `BaseQuantities.NetArea`, `Surface`, `Nombre`, `Couleur`.
- `Planchers`:
  - table lignes 1 a 23, colonnes A a H;
  - en-tetes: `Composant`, `Type`, `Étage`, `BaseQuantities.NetArea`, `Surface IFC OpenShell`, `Ecart`, `Nombre`, `Couleur`;
  - formules `F2:F20 = IF(En-Dn=0,"",En/Dn-1)`;
  - `D22 = SUM(D2:D21)`, `E22 = SUM(E2:E21)`, `E23 = E22/D22-1`.
- Donnees obligatoires:
  - dalles/planchers, principalement `IfcSlab`, eventuellement `IfcCovering` si la maquette code certains planchers ainsi;
  - type, etage, `BaseQuantities.NetArea`, surface IFC OpenShell, nombre.
- Verdict disponibilite:
  - BIMData snapshot: probablement bon pour `IfcSlab` + `NetArea` si les quantites sont presentes;
  - mode template MOA: requis pour la reproduction stricte;
  - code actuel: rapport inclus dans le pack.

## Contrat MCP a ajouter

Ajouter un tool sans effet de bord:

```python
@mcp.tool()
def list_avp_i3f_xls_reports(
    include_templates: bool = True,
    require_identical: bool = False,
) -> dict:
    ...
```

Sortie attendue:

```json
{
  "status": "ok",
  "project": {"name": "...", "code": "...", "phase": "AVP"},
  "reports": [
    {
      "key": "menuiseries",
      "label": "export Menuiseries",
      "can_generate": true,
      "can_generate_identical": false,
      "status": "partial",
      "available_data": ["IfcWindow", "BaseQuantities.Width", "BaseQuantities.Height"],
      "missing_data": [],
      "template_path": "/.../260130 Tarare export Menuiseries.xlsx",
      "source_xlsx_required_for_identical": true,
      "next_action": "Rapport metier generable depuis la maquette ; reproduction a l'identique indisponible sans mode template MOA."
    }
  ]
}
```

Etendre le tool existant:

```python
def generate_avp_i3f_pack(
    ...,
    mode: Literal["bimdata_branded", "moa_template"] = "bimdata_branded",
    reports: list[str] | None = None,
    plancher_xlsx: str | None = None,
    strict_identical: bool = False,
) -> dict:
    ...
```

Regles:

- `bimdata_branded`: maquette-first ; les surfaces/dimensions proviennent du snapshot IFC/OpenShell.
- `moa_template`: copie le workbook template, remplace uniquement les plages de donnees, conserve feuilles, largeurs, hauteurs, styles, formules, formats, tableaux croises et onglets vides.
- `strict_identical=True`: echoue si une colonne requise n'est pas disponible. Ne pas remplir avec `NOT_AVAILABLE` dans ce mode.
- Si `require_identical=True` dans le listing, un rapport est `ready` seulement si le mode template MOA peut preserver formules, pivots, styles et signatures.

## Architecture a implementer

1. Creer `audit_bim/reporting/avp_report_catalog.py`.
   - Dataclasses: `ReportSpec`, `DataRequirement`, `ReportAvailability`.
   - Un spec par rapport, avec cle, libelle, fichier exemple, feuilles attendues, en-tetes, formules critiques, donnees requises.

2. Creer `audit_bim/reporting/avp_availability.py`.
   - Fonction `inspect_avp_report_availability(snapshot, sources, require_identical=False)`.
   - Les probes doivent verifier les entites IFC et les proprietes, pas seulement la presence du snapshot.
   - Sortie serialisable MCP, stable et orientee utilisateur.

3. Creer `audit_bim/reporting/avp_moa_template.py`.
   - Utiliser `openpyxl` pour charger le template.
   - Preserver tout le workbook: `Workbook.copy_worksheet` ou copie fichier puis mutation ciblee.
   - Remplacer les lignes metier par rapport, en conservant:
     - noms d'onglets;
     - en-tetes;
     - styles de cellules;
     - largeurs colonnes/hauteurs lignes;
     - formules relatives;
     - onglets vides.

4. Ajouter `plancher` au modele:
   - `AvpSources.plancher`
   - `AvpSourcePaths.plancher`
   - lecteur `read_plancher`
   - builder snapshot `build_plancher_from_snapshot`
   - entree dans `_DELIVERABLE_LABELS`
   - champ dans `AvpReportPack`
   - sortie dans `generate_avp_i3f_pack`
   - QA gate dediee.

5. Ajouter un tool MCP `list_avp_i3f_xls_reports`.
   - Ce tool est l'etape que le MCP doit appeler avant generation client.
   - Il doit expliquer pourquoi un rapport est pret, partiel, ou bloque.

## Disponibilite des donnees dans le repo aujourd'hui

| Famille de donnees | Disponible aujourd'hui | Commentaire |
| --- | --- | --- |
| `IfcSpace`, surfaces nettes/brutes, zones, etages | Oui si le snapshot BIMData expose les relations et BaseQuantities | Deja utilise dans `avp_snapshot.py` |
| `IfcZone` et relation zone-espace | Oui, avec repli par `structure_tree` | Deja implemente |
| Murs d'enveloppe par layer `Extérieurs périphériques` | Oui si layers extraits | Deja implemente |
| Menuiseries portes/fenetres | Oui | `IfcWindow`, `IfcDoor` et variantes StandardCase deja gerees |
| Materiaux | Oui partiel | Depend de `material_list`/`materials` |
| Dalles/planchers | Non dans le pack AVP | A ajouter via `IfcSlab` |
| Surfaces et dimensions IFC OpenShell | Oui si quantites IFC extraites/calculables | Source metier des rapports generes |
| Tableaux croises Excel natifs | Non reconstruits strictement | Utiliser template ou source XLS |
| Styles MOA exacts | Non | Generation actuelle applique la charte BIMData |

## Criteres d'acceptation

Un rapport `moa_template` est accepte seulement si:

- les noms d'onglets correspondent exactement a l'exemple;
- les en-tetes correspondent exactement, accents et retours ligne compris;
- les formules critiques sont presentes aux memes emplacements logiques;
- les largeurs/hauteurs principales sont conservees;
- les onglets vides de reference restent presents;
- le nombre de lignes metier est coherent avec les donnees source;
- le mode strict echoue explicitement si une donnee IFC ou une signature template requise est absente;
- aucune valeur metier n'est inventee.

Ajouter des tests unitaires de signature workbook a partir de mini-fixtures:

- comparaison `sheetnames`;
- comparaison des en-tetes par sheet;
- comparaison des formules critiques;
- comparaison du statut de disponibilite pour snapshot-only, source-only et hybride;
- test `plancher` inclus dans le pack.

## Verdict operationnel

Le MCP peut deja proposer une partie du pack AVP et generer des XLS exploitables. Pour satisfaire la demande "a l'identique", il faut livrer le catalogue + availability check + mode template avant d'annoncer la capacite comme terminee.

Priorite de dev:

1. Ajouter `list_avp_i3f_xls_reports`.
2. Ajouter `plancher`.
3. Ajouter `moa_template` pour les cinq XLS joints.
4. Mettre la QA signature en gate obligatoire pour `strict_identical=True`.
