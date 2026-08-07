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
`read_evidence` se rabat sur `_validate_shape_degraded` : schéma déclaré, listes
`objects`/`spaces`, entrées de type objet. Ce repli **ne réimplémente pas le
schéma** — c'est un garde-fou qui refuse proprement ce qui n'est manifestement
pas exploitable, au lieu de laisser planter un `AttributeError` illisible. Le
jour où `bim-core>=0.4` est installé, la validation complète reprend sans
changer une ligne d'appel.

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

| Compteur | Contrôles distincts |
|---|---:|
| `controls_total` (lignes du classeur) | 413 |
| `logical_controls` | 286 |
| `metric_rule_candidates` (noyau Domo-0) | 30 |
| `rules_claimed` (registre) | 6 règles |
| **`geometry_evaluable_now`** | **16** |
| `geometry_blocked_axis_required` | 1 |
| `mapping_required` | 10 |
| `manual_or_judgement` | 229 |

Répartition complète — distincts / lignes :

| Statut | Distincts | Lignes |
|---|---:|---:|
| `evaluable_by_spatial_evidence` | 16 | 24 |
| `evaluable_with_object_mapping` | 10 | 16 |
| `non_evaluable_axis_required` | 1 | 1 |
| `non_evaluable_geometry_missing` | 5 | 10 |
| `non_evaluable_not_modeled` | 25 | 45 |
| `manual_review_required` | 182 | 240 |
| `advisory_only` | 47 | 77 |

### L'entonnoir, qui est le résultat à retenir

| Lecture | Chiffre | Ce qu'elle vaut |
|---|---:|---|
| Route lexicale `needs_geometry` (Domo-0) | 331 / 413 = **80 %** | sans valeur — « présence » et « accès » saturent |
| Noyau outillable (Domo-0) | 30 / 286 = **10 %** | grandeur + seuil, sans appréciation |
| **Évaluable aujourd'hui (Domo-2)** | **16 / 286 = 5,6 %** | règle revendiquée **et** champ renseigné |

Le passage de 10 % à 5,6 % n'est pas une déception : c'est la seconde porte qui
fait son travail. Le premier chiffre décrit des phrases, le second décrit un
document mesuré.

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
| `tests/unit/test_domofrance_coverage.py` | 17 tests, **tous en CI**, sans fichier client |
| `docs/scope-domofrance-coverage.md` | ce document |
