"""Adaptateur stable d'un élément modélisé.

:class:`BimObject` est la *vue normalisée* d'un élément BIMData (ou DOE,
ou ezdxf, ou tout autre source) consommée par les couches d'analyse et
de filtrage. Il est **immuable** (Pydantic ``frozen=True``) et
sérialisable JSON.

Conception
----------

- Les champs sont **plats** (pas de dict imbriqué dans les filtres) pour
  permettre un filtrage `O(1)` sans déballer de structures complexes.
- ``base_quantities`` et ``properties`` restent en dict pour les valeurs
  numériques / strings (clé = nom de propriété, valeur = value brute).
- Les classifications existantes sont une liste de :class:`ClassificationRef`
  — un élément peut porter plusieurs classifications (UniFormat II + 3F
  par exemple).
- Les champs spatiaux (``storey_*``, ``zone_*``, ``space_*``) restent
  *informatifs* : un BimObject sans rattachement spatial n'est pas
  invalide (typique des éléments hors hiérarchie).

Construction
------------

Les :class:`BimObject` sont produits par :func:`audit_bim.query.views.iter_bim_objects`
en lecture seule depuis :class:`audit_bim.extraction.model_data.ModelSnapshot`.
On ne stocke pas une copie de tout le snapshot — on génère lazy à la
demande des tools de filtrage.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ClassificationRef(BaseModel):
    """Référence à une classification associée à un :class:`BimObject`.

    Champs minimaux pour qu'un filtre de classification fonctionne sans
    dépendre du catalogue UniFormat / Omniclass / 3F côté domain.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    code: str
    label: str | None = None
    system: str | None = Field(
        None,
        description="Système de classification ('uniformat', 'omniclass', 'ccs', '3f' …).",
    )

    @property
    def level_3(self) -> str:
        """Niveau 3 UniFormat / équivalent (4 premiers caractères du code).

        Exemple : ``"B2010"`` pour ``"B2010.10"`` ou ``"B2010"``.
        """
        c = (self.code or "").strip().upper()
        # UniFormat : 1 lettre + 4 chiffres = 5 caractères. On normalise
        # les codes avec suffixe (séparé par . ou -) sur ces 5 premiers.
        if len(c) >= 5 and c[0].isalpha() and c[1:5].isdigit():
            return c[:5]
        return c


class BimObject(BaseModel):
    """Vue normalisée d'un élément modélisé, indépendante de la source.

    Attributes:
        uuid: GlobalId IFC (clé primaire stable).
        ifc_type: Classe IFC réelle (``IfcWallStandardCase``, …).
        name: Nom IFC court (``Name``).
        long_name: Nom long (``LongName``) si présent.
        object_type: Attribut ``ObjectType`` (souvent porteur de typologie
            Revit).
        predefined_type: ``PredefinedType`` IFC normalisé.
        description: Description libre.

        storey_uuid: GlobalId IFC de l'étage de rattachement.
        storey_name: Nom de l'étage (pour le filtrage lisible).
        zone_uuid: GlobalId IFC de la zone (logement).
        zone_name: Nom de la zone.
        space_uuid: GlobalId IFC de l'espace (pièce).
        space_name: Nom de l'espace.

        is_external: Pset_*Common.IsExternal (None = inconnu).
        load_bearing: Pset_*Common.LoadBearing (None = inconnu).

        layers: Calques source (Revit/CAO) — liste de noms uniques.
        materials: Matériaux assignés — liste de noms uniques.

        classifications: Classifications déjà associées à l'élément
            (peut être vide).
        properties: Dict ``{pset.prop: value}`` aplati pour filtres
            ``has_property`` / ``missing_property``. Les clés sont
            normalisées au format ``"PsetName.PropName"``.
        base_quantities: ``BaseQuantities`` extraites (``NetArea``,
            ``Height``, ``GrossVolume`` …) — valeurs numériques.

        source: Origine du BimObject (``"bimdata"``, ``"doe"``, ``"ifc"``).
            Permet le filtrage `source=bimdata` en tranche 2.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    uuid: str
    ifc_type: str | None = None
    name: str | None = None
    long_name: str | None = None
    object_type: str | None = None
    predefined_type: str | None = None
    description: str | None = None

    storey_uuid: str | None = None
    storey_name: str | None = None
    zone_uuid: str | None = None
    zone_name: str | None = None
    space_uuid: str | None = None
    space_name: str | None = None

    is_external: bool | None = None
    load_bearing: bool | None = None

    layers: list[str] = Field(default_factory=list)
    materials: list[str] = Field(default_factory=list)

    classifications: list[ClassificationRef] = Field(default_factory=list)
    properties: dict[str, Any] = Field(default_factory=dict)
    base_quantities: dict[str, float] = Field(default_factory=dict)

    source: str = "bimdata"

    # ── Helpers de filtrage ──────────────────────────────────────────────

    def has_property(self, key: str) -> bool:
        """``True`` si la clé ``"Pset.Prop"`` est présente *et* non vide.

        Args:
            key: Clé propriété au format ``"PsetName.PropName"``
                (matching insensible à la casse).
        """
        target = key.lower()
        for k, v in self.properties.items():
            if k.lower() == target:
                # vide = None ou string vide ; 0 / False sont considérés "présents"
                return not (v is None or (isinstance(v, str) and not v.strip()))
        return False

    def classification_codes(self, system: str | None = None) -> list[str]:
        """Liste des codes de classification associés (optionnellement
        filtrés par système).

        Args:
            system: Système à filtrer (``"uniformat"``, ``"omniclass"``,
                ``"ccs"``, ``"3f"``) — None = tous. Matching insensible
                à la casse.
        """
        if system is None:
            return [c.code for c in self.classifications]
        s = system.lower()
        return [c.code for c in self.classifications if (c.system or "").lower() == s]

    def has_classification(self, *, system: str | None = None) -> bool:
        """``True`` si l'élément a au moins une classification (optionnellement
        filtré par système)."""
        return bool(self.classification_codes(system=system))

    def compact_dict(self) -> dict[str, Any]:
        """Représentation compacte JSON-compatible pour retour MCP.

        Ne sérialise pas ``properties`` ni ``base_quantities`` complets
        (volumineux) — on garde uniquement les clés d'identification +
        rattachement spatial + classifications.
        """
        return {
            "uuid": self.uuid,
            "ifc_type": self.ifc_type,
            "name": self.name,
            "storey": self.storey_name,
            "zone": self.zone_name,
            "space": self.space_name,
            "is_external": self.is_external,
            "classifications": [{"code": c.code, "system": c.system} for c in self.classifications],
            "n_properties": len(self.properties),
            "source": self.source,
        }
