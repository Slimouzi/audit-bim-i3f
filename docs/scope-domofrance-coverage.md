# Scope — couverture Domofrance × `spatial_evidence/v1` (Domo-2)

Croise la liste de contrôle Domofrance inventoriée en Domo-0 avec un document de
preuves géométriques réellement produit, et dit pour chaque contrôle **s'il
pourra être tranché**. Jamais s'il est conforme.

Aucun profil MCP, aucun outil MCP, aucune lecture de maquette : le script lit un
classeur et un JSON. Suite de Domo-0
(`docs/scope-domofrance-controls.md`).

## Contrat publié, non encore adopté par ce dépôt

`spatial_evidence/v1` existe et est publié :

| Brique | Tag | État |
|---|---|---|
| Contrat | `bim-core-v0.4.0` | publié, 89 tests |
| Producteur `extract_spatial_evidence` | `ifc-geometry-mcp-v0.6.0` | publié, 101 tests |
| **Consommateur `audit-bim-mcp`** | — | **non adopté**, épingle `bim-core>=0.3.0,<0.4` |

L'adoption n'est pas un bump : cinq paquets first-party
(`bimdata-read`, `bim-query`, `bim-publication`, `bim-audit-engine`,
`bimdata-write`) contraignent `bim-core<0.4`. La faire maintenant casserait le
resolver ou imposerait un `[tool.uv.override]` — c'est-à-dire exactement la
dette soldée volontairement. Elle est donc reportée au moment où `audit_bim/`
consommera réellement `spatial_evidence`.

**Conséquence assumée : la validation est dégradée.** Dans ce dépôt et en CI,
`from bim_core.contracts import parse_spatial_evidence` échoue, et
`read_evidence` se rabat sur `_validate_shape_degraded`. Le jour où
`bim-core>=0.4` est installé, la validation complète reprend sans changer une
ligne d'appel.

### Ce que le repli valide, et pourquoi il n'est pas seulement structurel

Une première version ne vérifiait que la forme des conteneurs : schéma déclaré,
`objects`/`spaces` listes de dicts. C'était insuffisant, et pas théoriquement :
`read_evidence` compte un champ comme renseigné dès qu'il n'est pas `None`.
Un document portant `opening_width_m: "large"` ou `bbox: {}` aurait donc rendu
un contrôle **« évaluable » sans qu'aucune mesure exploitable existe** — dans le
seul mode de validation actuellement disponible.

Le repli valide donc aussi **les champs réellement consommés** :

| Vérification | Règle |
|---|---|
| `ifc_class` | chaîne non vide, obligatoire |
| `opening_width_m`, `clear_height_m`, `area_declared_m2`, `inscribed_diameter_m`, `occupancy_area_m2`, `min_rect_width_m` | nombre **fini** si présent — ni texte, ni booléen, ni `nan`/`inf` |
| `bbox` | si présente : six bornes, toutes numériques finies |
| Message | nomme le fichier, la collection, l'index et le champ |

Un champ **absent ou `null` reste licite** : c'est une mesure manquante, pas un
document invalide — et c'est précisément ce que le rapport doit pouvoir compter
(`non_evaluable_geometry_missing`). Le booléen est exclu explicitement : en
Python `True` est un `int`, et `opening_width_m: true` passerait pour une
largeur de 1 m.

Ce repli **ne réimplémente pas le schéma**. Il ferme la fausse évaluabilité sur
les champs dont dépendent les verdicts, et laisse le reste au contrat.

## Le point du lot : deux conditions, pas une

Un contrôle n'est déclaré évaluable qu'après **deux** portes :

1. une **règle explicite du registre** le revendique — chaque règle nomme le
   champ du contrat qu'elle lirait, et le rapport liste combien de contrôles
   elle revendique, donc c'est auditable ;
2. ce champ est **effectivement renseigné** dans le document de preuves fourni,
   pour la classe visée.

La seconde porte est ce qui distingue Domo-2 d'un classeur de mots-clés :
l'évaluabilité dépend du document mesuré, pas du vocabulaire du contrôle.

## Le cas qui justifie la seconde porte

Sur la maquette de référence, cinq contrôles d'emmarchement (« giron ≥ 28 cm »)
sont revendiqués par la règle `emmarchement`. Le classement lexical les
annoncerait évaluables : la phrase porte une grandeur et un seuil chiffré.

Le document dit autre chose. Il contient bien **24 `IfcStair`** — donc « pas
d'escalier dans la maquette » est faux — mais `bbox` y est renseignée sur
**0** d'entre eux. Statut rendu : `non_evaluable_geometry_missing`, et non
`non_evaluable_not_modeled`. Les deux causes n'appellent pas la même action :
l'une est une lacune de maquette, l'autre un périmètre d'extraction à élargir.

## Les sept statuts

Aucun ne porte de verdict ; un test l'interdit (`test_le_document_ne_decide_jamais_de_la_conformite`).

| Statut | Sens |
|---|---|
| `evaluable_by_spatial_evidence` | règle + champ renseigné : tranchable |
| `evaluable_with_object_mapping` | seuil et contexte spatial, mais l'objet visé reste à mapper |
| `non_evaluable_axis_required` | largeur d'espace non convexe : demande un axe médian |
| `non_evaluable_geometry_missing` | classe présente, champ jamais renseigné |
| `non_evaluable_not_modeled` | classe absente, ou objet qu'aucune classe IFC ne décrit |
| `manual_review_required` | aucune règle applicable — **le défaut** |
| `advisory_only` | vocabulaire d'appréciation du maître d'ouvrage |

**L'ordre des tests est la politique.** L'appréciation prime sur tout : « il est
recommandé que les boîtes aux lettres soient à l'intérieur du hall » porte une
géométrie parfaitement mesurable et reste une préférence. Trancher
« non conforme » là-dessus contredirait le document du client. Le vocabulaire
consultatif est **celui de Domo-0**, pas une seconde liste — un test le vérifie,
deux listes divergeraient sans que rien ne le signale.

## Mesure sur la maquette de référence

Document : `250613_MN_BAT_spatial_evidence.json`, produit par `ifc-geometry`
**0.5.1** (antérieur au tag v0.6.0 ; le garde-fou `source.version >= 0.6.0` est
reporté avec l'adoption). 12 classes présentes, 316 `IfcSpace` dont **246
convexes**, 300 `IfcDoor` dont 300 avec `opening_width_m`.

> Cette maquette n'est **pas** un bâtiment Domofrance : c'est le fichier de
> référence disponible. Les compteurs ci-dessous montrent le mécanisme sur un
> document réel, pas la couverture d'une affaire Domofrance.

| Compteur | Valeur |
|---|---:|
| `controls_total` (lignes du classeur) | 413 |
| `logical_controls` | 286 |
| `metric_rule_candidates` (noyau Domo-0) | 30 |
| `rules_claimed` (registre) | 6 règles |
| **`geometry_evaluable_in_core`** (base cadrée) | **13 / 30** |
| `geometry_evaluable_now` (tous distincts) | 16 / 286 |
| `geometry_blocked_axis_required` | 1 |
| `mapping_required` | 11 |
| `manual_or_judgement` | 229 |

Répartition complète — distincts / lignes :

| Statut | Distincts | Lignes |
|---|---:|---:|
| `evaluable_by_spatial_evidence` | 16 | 24 |
| `evaluable_with_object_mapping` | 11 | 18 |
| `non_evaluable_axis_required` | 1 | 1 |
| `non_evaluable_geometry_missing` | 5 | 10 |
| `non_evaluable_not_modeled` | 24 | 43 |
| `manual_review_required` | 182 | 240 |
| `advisory_only` | 47 | 77 |

### Deux dénominateurs, tous deux publiés — note de delta

La base de référence du lot est le **noyau Domo-0** : **13 évaluables sur 30**.
C'est ce compteur qui se compare aux mesures antérieures.

Le rapport publie aussi `16 / 286`, sur l'ensemble des contrôles distincts. Les
deux sont exacts et **ne mesurent pas la même chose** : l'écart de 3 vient de
contrôles qu'une règle revendique alors qu'ils ne portent **pas de seuil
chiffré**, donc absents du noyau.

| Ligne | Règle | Pourquoi hors noyau |
|---|---|---|
| L18 | `encombrement_local` | « Vérifiez la présence des équipements dans le hall » — aucun seuil |
| L25 | `encombrement_local` | « Vérifiez la position des boîtes aux lettres » — aucun seuil |
| L416 | `surface_local` | « Vérifer la surface vitrée » — aucun seuil |

Publier `16 / 286` seul aurait fait passer un **changement de base** pour un
mouvement de couverture. Les deux figurent donc côte à côte dans le rapport
comme dans ce document, et `geometry_evaluable_in_core` porte la mention
« base cadrée ».

### L'entonnoir, qui est le résultat à retenir

| Lecture | Chiffre | Ce qu'elle vaut |
|---|---:|---|
| Route lexicale `needs_geometry` (Domo-0) | 331 / 413 = **80 %** | sans valeur — « présence » et « accès » saturent |
| Noyau outillable (Domo-0) | 30 / 286 | grandeur + seuil, sans appréciation |
| **Évaluable aujourd'hui, dans le noyau** | **13 / 30 = 43 %** | règle revendiquée **et** champ renseigné |

Sur le noyau, 13 des 30 contrôles réellement métriques sont tranchables avec le
document fourni. Les 17 autres butent sur une géométrie absente, un axe médian
requis, ou un objet à mapper — pas sur le vocabulaire.

## Le registre des règles

Six règles, chacune nommant le champ qu'elle lirait — donc chacune réfutable.

| Règle | Champ lu | Classe | Revendique | Sur la maquette |
|---|---|---|---:|---|
| `porte_largeur_passage` | `opening_width_m` | `IfcDoor` | 6 | disponible |
| `hauteur_sous_plafond` | `clear_height_m` | `IfcSpace` | 2 | disponible |
| `surface_local` | `area_declared_m2` | `IfcSpace` | 6 | disponible |
| `largeur_espace` | `inscribed_diameter_m` | `IfcSpace` | 1 | disponible |
| `emmarchement` | `bbox` | `IfcStair` | 5 | **ABSENT** |
| `encombrement_local` | `occupancy_area_m2` | `IfcSpace` | 2 | disponible |

`largeur_espace` porte `needs_convexity` : le cercle inscrit ne vaut la largeur
que sur un espace **convexe**. Sur un L à branches de 2,00 m il rend 2,338 quand
le rectangle orienté rend 6,00 — aucun des deux n'est la largeur du passage.
Un espace est tenu pour convexe quand le rapport des deux mesures atteint
`CONVEXITY_RATIO_MIN = 0.95`.

### La rampe d'accès n'est pas « non modélisable »

`« rampes d'accès »` figurait dans `_UNMODELLED`, la liste des objets qu'aucune
classe IFC ne porte. C'était **faux sur le fond** : `IfcRamp` existe, et une
rampe se modélise. Le motif a été retiré.

Aucune règle ne la revendique pour autant : `spatial_evidence/v1` n'offre aucun
champ donnant la largeur d'un objet quelconque — `opening_width_m` ne vaut que
pour les menuiseries. Le contrôle « les rampes d'accès auront une largeur
minimale de 3,00 m » retombe donc sur le défaut et sort en
`evaluable_with_object_mapping` : *l'objet visé reste à mapper*. C'est un statut
honnête, qui dit ce qui manque au lieu d'affirmer une impossibilité.

Une règle `IfcRamp` deviendra pertinente le jour où le contrat portera une
largeur d'objet — pas avant, sous peine de revendiquer un champ inexistant.

## Seuils indicatifs, seuils opposables

Les deux tables de surfaces sont légendées « souhaitable » — « à titre
indicatif » pour le collectif. Les ranger avec les colonnes `LARGEUR MINI`,
annoncées « dimension minimales » dans la **même** légende, produirait des
« non conforme » sur des valeurs que le client ne présente pas comme opposables.
`surface_natures` sépare donc `surface_target_advisory` de
`width_min_mandatory`, et trois tests interdisent de les fondre.

## Auto-audit

Le rapport liste les contrôles du **noyau Domo-0 qu'aucune règle ne
revendique** : c'est la liste de ce que le registre laisse encore passer, et
donc la matière du prochain lot de règles. Sans elle, un registre pauvre
paraîtrait complet.

## Ce que ce lot ne fait pas

- Aucun statut de conformité, aucune maquette jugée.
- Aucun profil ni outil MCP ; aucune dépendance nouvelle.
- **Aucune adoption de `bim-core>=0.4`** — reportée au fan-out first-party.
- Aucun garde-fou `source.version` : il viendra avec l'adoption.

## Fichiers

| Fichier | Rôle |
|---|---|
| `scripts/coverage_domofrance_controls.py` | couverture — `--csv` pour relecture |
| `tests/unit/test_domofrance_coverage.py` | 30 tests, **tous en CI**, sans fichier client |
| `docs/scope-domofrance-coverage.md` | ce document |
