# Diagnostic des Psets MRN manquants

**Lot 183.** Mesure uniquement : aucun statut de conformité, aucune écriture dans
la grille MRN, aucun mapping appliqué.

Ce document devait préparer une convention de mapping. La mesure a changé son
objet : **le principal livrable est le constat que le `Pset_MRN` n'a pas été
saisi**, pas une table de correspondance.

## Base officielle

| | Exigences |
|---|---:|
| Bloquées en `non_evaluable_mapping_pset` | **197** |
| Propriété exacte retrouvée sur classe compatible | **21** |
| Aucun candidat exact | **176** |

Gain théorique **plafonné à 21 exigences, sous validation humaine**. Aucun n'est
acquis.

## Trois lectures fausses, et pourquoi elles l'étaient

Ce chiffre de 21 est le quatrième. Les trois précédents ne sont pas des erreurs
de calcul : chacun répondait à une question plus facile que celle qui comptait.

**197 — le total brut.** « Le mapping débloquerait 197 exigences. » Le nombre
d'exigences bloquées *par un problème de Pset* n'est pas le nombre d'exigences
*qu'un mapping résout*. Un total ne dit rien de sa composition.

> **Anti-règle** : ne jamais annoncer un gain égal à la taille d'une population
> d'échecs. La cause du blocage n'est pas la preuve qu'il existe un remède.

**22 — la séparation par nom de Pset.** Les 197 se répartissaient en 175
`Pset_MRN` et 22 `Qto_*`. J'en ai conclu que `Pset_MRN` était intégralement
absent et que seuls les 22 étaient mappables. Je n'avais pas vérifié : certaines
propriétés attendues sous `Pset_MRN` portent des noms IFC standards, présents
ailleurs.

> **Anti-règle** : le nom du Pset attendu ne dit pas si la donnée existe. Une
> classification par libellé n'est pas une mesure.

**54 — le recouvrement de groupe.** En cherchant si un Pset présent contenait
*au moins une* propriété attendue, 54 exigences trouvaient un candidat. Mais un
`Pset_WindowCommon` qui porte `IsExternal` — une propriété sur les quinze
attendues — ne rend pas les vingt-cinq exigences évaluables.

> **Anti-règle** : un critère de groupe transfère la preuve d'une exigence à ses
> voisines. Le score doit être local à ce qu'on prétend débloquer.

**21 — la propriété exacte, sur classe compatible.** La seule question qui
engage : *cette propriété-là existe-t-elle sur cette classe-là ?*

## Ce que montre `IfcWindow` / `Pset_MRN`

| | |
|---|---|
| Exigences du groupe | 25 |
| Propriétés distinctes attendues | 15 |
| `group_overlap_rate` | **0,07** (1 propriété sur 15) |
| Candidats exacts | **1** |

Une convention écrite au niveau du groupe aurait déclaré 25 exigences mappables
sur la foi d'un seul `IsExternal`. Le taux de recouvrement est conservé comme
**diagnostic** — il signale qu'un rapprochement existe — mais il ne débloque
rien.

## Ventilation par Pset attendu

Sortie de `scripts/inventory_mrn_pset_gap.py` — exigences **couvertes / total** :

| Pset attendu | Couvertes / total |
|---|---:|
| `Pset_MRN` | **4 / 175** |
| `Qto_WindowBaseQuantities` | 10 / 10 |
| `Qto_DoorBaseQuantities` | 6 / 7 |
| `Qto_WallBaseQuantities` | 1 / 1 |
| `Pset_DistributionFlowElementCommon` | 0 / 2 |
| `Pset_CoveringCommon` | 0 / 2 |

Cette ventilation existe pour empêcher une phrase : **« `Pset_MRN` a des
candidats »**. Elle est vraie et trompeuse — quatre exigences sur cent
soixante-quinze. Toute mention de candidats pour `Pset_MRN` doit porter le
rapport, jamais le seul fait qu'il en existe.

Les quantités, à l'inverse, sont presque intégralement couvertes : 17 sur 18.

## Forme des candidats

Un candidat porte sur **une exigence**, jamais sur un couple de Psets :

```
candidate_source_pset      Pset présent dans la maquette
required_property          propriété exigée par le MRN
matched_property           propriété trouvée, normalisée à la casse
same_ifc_scope             classe visée ou sous-classe acceptée
confidence                 1.0 — propriété exacte, classe compatible
requires_human_validation  toujours True
```

Aucun candidat n'est produit si la propriété exacte est absente. La signature
porte ainsi sur une correspondance nommée, pas sur une équivalence supposée entre
deux jeux de propriétés.

## Les 176 sans candidat

`Pset_MRN` attend **131 propriétés distinctes** — `Affectation_Local`,
`Accessibilite_PMR`, `Acces_pompier`, `Additif`… La quasi-totalité n'existe nulle
part dans la maquette.

| Feuille | Exigences `Pset_MRN` |
|---|---:|
| Gros Oeuvre - CEA | 84 |
| Généralités | 61 |
| VRD-Extérieur | 26 |
| CVC-PLB-SSI-ELEC | 4 |

Ce n'est pas un écart de vocabulaire : **la donnée n'a pas été renseignée**.
Aucun fichier de correspondance ne crée ce qui n'a pas été saisi.

## Conclusion

> `Pset_MRN` est absent comme **structure contractuelle** ; quelques propriétés
> existent ailleurs, mais elles ne valent pas convention de mapping sans
> validation exigence par exigence.

La suite n'est pas un lot technique. C'est un arbitrage : **faire signer les 21
correspondances**, ou **demander une maquette enrichie du `Pset_MRN`**. La
seconde voie répond à 176 exigences, la première à 21 au mieux.

## Reproduire

```bash
python scripts/inventory_mrn_pset_gap.py <table_attributs.xlsx> <url_viewer>
```

Le tableau de ventilation ci-dessus est la sortie de cette commande, pas une
saisie manuelle. La CI ne peut pas le recalculer : elle n'a ni le fichier MRN
ni l'acces BIMData. Le test ne fige donc que la **forme** imposee au document
(le rapport `4 / 175`, jamais « a des candidats » seul) et le fait que le
script compte par exigence. Les valeurs se reverifient en rejouant le script.

Chiffres releves sur `250613_MN_BAT (2).ifc` — cloud 34140, projet 3281472,
modèle 1744293.
