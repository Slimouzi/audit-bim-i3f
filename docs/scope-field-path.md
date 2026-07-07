# Scope — `field_path` généralisé aux findings non-zone (#5)

But : étendre le champ structuré `Finding.field_path` (aujourd'hui émis **seulement**
par les règles Zone de `naming.py`, consommé par `avp_i3f._zone_finding_kind`) à
**tous** les findings, avec un **format gelé**, pour remplacer à terme les heuristiques
de wording par une discrimination structurée. **Décisions à figer avant tout code.**

## 1. Format gelé (grammaire)

`field_path` est une chaîne pointée décrivant **l'emplacement du défaut** sur l'objet
IFC. Trois formes, et **une seule** exemption :

| Forme | Grammaire | Exemple | Cas |
|---|---|---|---|
| **Attribut** | `<IfcClass>.<Attribut>` | `IfcSpace.Name`, `IfcZone.ObjectType` | attribut IFC direct (Name, LongName, ObjectType…) |
| **Propriété** | `<IfcClass>.<Pset>.<Prop>` | `IfcDoor.Pset_DoorCommon.FireRating` | property set |
| **Quantité** | `<IfcClass>.<Qto>.<Quantity>` | `IfcSpace.Qto_SpaceBaseQuantities.NetFloorArea` | quantity set (sous-cas de la forme propriété) |
| **Exemption** | `None` | — | défaut **non rattachable à un champ unique** (voir §3) |

Règles : `IfcClass` = classe IFC réelle de l'objet (`IfcSpace`, `IfcZone`, `IfcDoor`,
`IfcWall`…) ; segments non vides ; pas d'espaces ; casse IFC exacte. **Pas** de valeur,
pas de GlobalId (déjà porté par `object_id`), pas de libellé humain.

## 2. Émission par famille (mapping figé)

| Fichier | error_type(s) | `field_path` |
|---|---|---|
| `naming.py` (non-zone) | NAMING_TOO_LONG / _INVALID_FORMAT / _MISSING / _NOT_IN_LIST | `<IfcClass>.<Attribut>` (attribut nommé contrôlé : `Name` ou `LongName`) |
| `naming.py` (zone, existant) | idem | `IfcZone.Name` / `IfcZone.ObjectType` (**inchangé**) |
| `properties.py` | PROPERTY_MISSING / PROPERTY_TYPE_INVALID | `<IfcClass>.<Pset>.<Prop>` |
| `lists.py` | NAMING_NOT_IN_LIST | `<IfcClass>.<Attribut>` (attribut vérifié contre la liste) |
| `uniqueness.py` | NAMING_MISSING / NAMING_INVALID_FORMAT | `<IfcClass>.<Attribut>` (identifiant, ex. `Name`) |
| `spatial.py` | SPATIAL_MISSING_QUANTITY / PROPERTY_MISSING | `<IfcClass>.<Qto>.<Quantity>` / `<IfcClass>.<Pset>.<Prop>` |
| `spatial.py` | SPATIAL_ORPHAN | **`None`** — exempté (cf. §3) |
| `classifications.py` | CLASSIFICATION_MISSING / CLASSIFICATION_INVALID | **`None`** — exempté (cf. §3) |
| `preliminary.py` | findings importés | **inchangé** (hors périmètre : findings externes, `field_path` tel qu'importé ou `None`) |

**Décision (gelée, CTO)** : classification et orphelin spatial → **`None`** (pas de
token relationnel). La grammaire §1 est un contrat « **champ résoluble sur le modèle
IFC** » ; un token comme `IfcSpace.SpatialContainment` y *ressemble* sans en être —
chaque consommateur devrait le spécial-caser, ce qui est pire qu'un `None` explicite.
Le principe « pas de consommateur spéculatif » (§5) s'applique : si un consommateur
**réel** apparaît un jour, on étendra la grammaire **délibérément** (famille
relationnelle dédiée, gelée à ce moment-là), pas par anticipation.

## 3. Exemption `None` — liste blanche **par error_type** (chacune justifiée)

`field_path=None` est réservé aux défauts non rattachables à un champ IFC unique. La
liste blanche est **par `error_type`** (pas par famille) et **exhaustive** : tout
`error_type` émettant `None` hors de cette table fait échouer le verrou (§4) — elle ne
peut donc pas grossir silencieusement. Ajouter une entrée = ajouter une ligne justifiée
ici, en revue.

| `error_type` exempté (`None`) | Justification (défaut sans champ IFC unique) |
|---|---|
| `SPATIAL_ORPHAN` | l'objet n'a **aucun** conteneur spatial — le défaut porte sur l'absence de relation, pas sur un attribut/pset. |
| `CLASSIFICATION_MISSING` | aucune référence de classification présente — rien à localiser par `<IfcClass>.…`. |
| `CLASSIFICATION_INVALID` | défaut sur la **référence de classification** (système/notation), pas un attribut ni un pset. |

`object_id` + `error_type` suffisent à situer ces trois défauts. Les findings
**importés** (`preliminary.py`, provenance externe) sont **hors périmètre** du verrou
(leur `field_path` est celui de l'import, éventuellement `None`).

## 4. Test de verrou générique (lock)

Un test unique, indépendant des règles, qui exécute un audit de référence et vérifie
pour **chaque** finding :

1. soit `field_path is None` **et** `error_type` ∈ liste blanche d'exemption (§3) ;
2. soit `field_path` respecte la grammaire (§1) : `re.fullmatch` sur
   `^Ifc[A-Za-z0-9]+(\.[A-Za-z0-9_]+){1,2}$`, premier segment = classe IFC de l'objet.

Objectif : rendre **impossible** l'ajout d'une règle qui émet un `field_path` mal formé
ou un `None` non exempté sans faire échouer la CI.

## 5. Consommation — principe

**Consommer uniquement là où un vrai consommateur existe.** Aujourd'hui : seul
`avp_i3f._zone_finding_kind` lit `field_path` (zone). On **n'ajoute pas** de consommateur
spéculatif : la généralisation de l'émission est un **investissement de contrat** (données
structurées disponibles), la migration des heuristiques de wording restantes vers
`field_path` se fera **au cas par cas quand un besoin réel se présente**, pas dans ce lot.

## 6. Ordre d'exécution (après gel de ce scope)

1. Gel §1–§3 (format + mapping + exemptions) — **cette PR, docs-only**.
2. Émission `field_path` dans les 6 familles + zones existantes inchangées.
3. Test de verrou générique (§4) + liste blanche d'exemption.
4. Suite offline verte ; **aucun** nouveau consommateur (§5).
