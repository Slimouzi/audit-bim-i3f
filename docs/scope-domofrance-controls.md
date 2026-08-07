# Scope — liste de contrôle Domofrance (Domo-0, inventaire)

Domofrance est le 3ᵉ maître d'ouvrage après I3F et BIM in Motion. Ce lot
**décrit son classeur**. Il n'ajoute aucun profil MCP, aucun outil MCP, ne lit
aucune maquette et n'émet aucun statut de conformité.

L'ordre de travail est celui arrêté par le CTO : **Excel → inventaire → preuve
géométrique → couverture → règles → livrable**, et non Excel → parser →
faisabilité. Motif : ne pas coder 413 cas particuliers dans un MCP client tant
que le socle géométrique ne produit pas de preuves réutilisables.

Source : `Liste de contrôle.xlsx`, feuilles `LISTE DE CONTROLE` et `SURFACE`.
Le classeur vit **hors du dépôt**.

## Comment lire les chiffres : `[CI]` / `[CLASSEUR]`

Chaque compteur ci-dessous porte sa provenance. La distinction n'est pas
cosmétique : elle dit lesquels de ces nombres restent prouvés quand le fichier
du client est absent — c'est-à-dire en intégration continue.

| Marqueur | Prouvé par | Sans le classeur |
|---|---|---|
| `[CI]` | la fixture de forme `tests/unit/domofrance_controls_shape.json`, extraite du vrai classeur et **anonymisée** (chaque libellé remplacé par un index stable) | **test vert** — le compteur reste prouvé |
| `[CLASSEUR]` | le texte réel du maître d'ouvrage | **test ignoré**, et il le dit |

La forme conserve la duplication et les décomptes de valeurs distinctes sans
emporter une seule phrase du client. C'est ce qui permet à `[CI]` de couvrir
toute la structure. En revanche, un agrégat lexical dépend des mots eux-mêmes :
il ne peut pas être reconstitué depuis des index, et rester silencieux là-dessus
ferait passer une suite verte pour une preuve — l'accident déjà rencontré sur le
gabarit MRN.

Reproduire :

```bash
python scripts/inventory_domofrance_controls.py "<…>/Liste de contrôle.xlsx"
python scripts/inventory_domofrance_controls.py "<…>/Liste de contrôle.xlsx" --csv > controls.csv
```

## Structure — feuille `LISTE DE CONTROLE`

| Compteur | Valeur | Provenance |
|---|---:|---|
| Lignes de contrôle (lignes 4 → 416) | **413** | `[CI]` |
| Lignes distinctes (5 colonnes) | **286** | `[CI]` |
| Distinctes hors `TYPE DE LOGEMENT` | **285** | `[CI]` |
| Types de logement distincts | 3 | `[CI]` |
| Zones distinctes | 57 | `[CI]` |
| Éléments distincts | 101 | `[CI]` |
| Libellés de vérification distincts | 198 | `[CI]` |
| Descriptions distinctes | 251 | `[CI]` |

Répartition : 391 `LOGEMENT COLLECTIF`, 21 `LOGEMENT INDIVIDUEL`, 1
`LOGEMENT COLLECTIF/INDIVIDUEL`.

**286 identités mais 285 contrôles** : un contrôle est écrit deux fois, une fois
par type de logement. Les deux lectures sont légitimes ; elles ne répondent
simplement pas à la même question.

### Duplication — deux compteurs, volontairement tous les deux publiés

| Compteur | Valeur | Provenance |
|---|---:|---|
| Lignes impliquées dans un groupe de doublons | **209** | `[CI]` |
| dont répétitions (hors 1ʳᵉ occurrence) = 413 − 286 | **127** | `[CI]` |
| Groupes de doublons | **82** | `[CI]` |
| Plus grand groupe | **7** | `[CI]` |

Une ligne présente 7 fois, c'est 7 lignes concernées et 6 répétitions. N'en
publier qu'un des deux invite à citer le mauvais nombre. Le parseur **ne
dédoublonne jamais** : les doublons appartiennent au document du client, les
écraser ferait disparaître un fait à lui rapporter.

## Signaux lexicaux — hypothèse d'outillage, **pas** une couverture

Quatre familles non exclusives, cherchées dans le texte normalisé
(`VÉRIFICATION` + `DESCRIPTION`). Un contrôle peut n'en porter aucune ou
plusieurs. Elles disent **quels mots porte le texte**, pas ce qu'il faut mesurer.

| Famille | Contrôles | Provenance |
|---|---:|---|
| `needs_bbox` | 99 | `[CLASSEUR]` |
| `needs_collision` | 15 | `[CLASSEUR]` |
| `needs_space_context` | 287 | `[CLASSEUR]` |
| `manual_only` | 77 | `[CLASSEUR]` |
| `needs_geometry` (dérivé : au moins un signal géométrique) | **331** | `[CLASSEUR]` |
| Seuil chiffré avec unité | 67 | `[CLASSEUR]` |
| Aucun signal | 67 | `[CLASSEUR]` |
| Signal géométrique **et** `manual_only` | 62 | `[CLASSEUR]` |

Le *mécanisme* de détection, lui, est `[CI]` : chaque famille est éprouvée sur
des phrases écrites dans le test, et un nombre sans unité (« format A2 »,
« 30% des boîtes ») est refusé comme seuil.

## Le résultat qui commande la suite : la route lexicale sature

`needs_geometry` sort à **331 / 413, soit 80 %**. Ce chiffre n'a **aucune
valeur** : il est porté par « présence » et « accès », deux mots qui traversent
presque tout le classeur sans rien rendre mesurable. Annoncer 80 % d'outillable
au client serait un chiffre crédible et faux.

Le noyau réellement outillable est la **conjonction stricte** de trois
conditions : une grandeur nommée, un seuil chiffré avec unité, et aucun
vocabulaire d'appréciation.

| Compteur | Valeur | Provenance |
|---|---:|---|
| Contrôles distincts | 286 | `[CI]` |
| **Noyau outillable** | **30** | `[CLASSEUR]` |
| Soit | **10,5 %** | `[CLASSEUR]` |

**30 sur 286, soit ~10 %** — c'est l'ordre de grandeur à annoncer. L'écart entre
80 % et 10 % est tout l'enjeu de ce lot.

## Tables de surfaces — feuille `SURFACE`

| | Collectif | Individuel | Provenance |
|---|---:|---:|---|
| Typologies | 6 (T1bis→T6) | 3 (T3→T5) | `[CI]` |
| Types de pièces | 13 | 13 | `[CI]` |
| Colonne `LARGEUR MINI` | oui | oui | `[CI]` |
| Cellules numériques | 53 | 27 | `[CI]` |
| Ligne de total | 19 | 19 | `[CI]` |

La ligne `Total` n'est pas un type de pièce : la compter en ferait 14 au lieu de
13.

## Deux pièges du classeur, à ne pas perdre

1. **La table collectif est légendée « … souhaitable … (à titre indicatif) »**
   `[CLASSEUR]`. Aucun verdict de conformité ne peut être rendu sur ces
   surfaces. La légende est une phrase du client : elle est absente de la
   fixture, donc ce constat n'existe que sous `needs_workbook`.
2. **La ligne 77 porte un gabarit non rempli** : « … ne devra pas être
   supérieure à 2,50 m de x% ». Le seuil n'est pas déterminé dans le document.

Une valeur comme `1,20/0,9` (deux largeurs dans une seule cellule) n'est pas un
nombre ; `2,5*` en est un, l'astérisque étant un renvoi de note.

## Ce que ce lot ne fait pas

- Aucun profil MCP Domofrance, aucun outil MCP.
- Aucune lecture de maquette, aucun `spatial_evidence`, aucun appel à
  `ifc-geometry`. La preuve géométrique est le lot suivant.
- Aucun statut de conformité, et jamais le mot « évaluable » : ce verdict
  suppose une preuve qui n'existe pas encore.

## Fichiers

| Fichier | Rôle |
|---|---|
| `scripts/inventory_domofrance_controls.py` | inventaire — `--summary` (défaut) et `--csv` |
| `tests/unit/test_domofrance_inventory.py` | 25 tests : 22 `[CI]` + 3 `[CLASSEUR]` |
| `tests/unit/domofrance_controls_shape.json` | forme anonymisée du classeur |
| `docs/scope-domofrance-controls.md` | ce document |
