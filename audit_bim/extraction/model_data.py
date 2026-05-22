"""Snapshot du modèle IFC nécessaire à l'audit.

L'audit n'exige qu'une vision *par classe IFC* + hiérarchie spatiale + Psets ;
on encapsule tout dans une structure ``ModelSnapshot`` immuable.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from .client import BIMDataClient


@dataclass
class ModelSnapshot:
    """Photo du modèle IFC à un instant t (en mémoire)."""

    project: dict = field(default_factory=dict)
    model: dict = field(default_factory=dict)
    sites: list[dict] = field(default_factory=list)
    buildings: list[dict] = field(default_factory=list)
    storeys: list[dict] = field(default_factory=list)
    spaces: list[dict] = field(default_factory=list)
    zones: list[dict] = field(default_factory=list)
    elements: list[dict] = field(default_factory=list)
    structure_tree: list[dict] = field(default_factory=list)

    # Index dérivés (construits dans `index()`)
    elements_by_type: dict[str, list[dict]] = field(default_factory=dict)
    element_by_uuid: dict[str, dict] = field(default_factory=dict)

    def index(self) -> "ModelSnapshot":
        """Construit les index pour accès O(1) par UUID et par classe IFC."""
        by_type: dict[str, list[dict]] = defaultdict(list)
        by_uuid: dict[str, dict] = {}
        # On regroupe TOUS les éléments dans le même index : Site/Building/
        # Storey/Space/Zone ne sont pas toujours présents dans /element/raw
        # selon la version du modèle ; on les ajoute donc explicitement.
        for el in self.elements:
            if t := el.get("type"):
                by_type[t].append(el)
            if u := el.get("uuid"):
                by_uuid[u] = el
        # Sites / Buildings / Storeys / Spaces / Zones : routes dédiées
        for kind, items in (
            ("IfcSite", self.sites),
            ("IfcBuilding", self.buildings),
            ("IfcBuildingStorey", self.storeys),
            ("IfcSpace", self.spaces),
            ("IfcZone", self.zones),
        ):
            for it in items:
                u = it.get("uuid")
                if u and u not in by_uuid:
                    by_uuid[u] = {**it, "type": kind}
                    by_type[kind].append({**it, "type": kind})
        self.elements_by_type = dict(by_type)
        self.element_by_uuid = by_uuid
        return self

    # ── Helpers ─────────────────────────────────────────────────────────────

    def of_class(self, ifc_class: str) -> list[dict]:
        return self.elements_by_type.get(ifc_class, [])

    def summary(self) -> dict[str, Any]:
        return {
            "project_name": (self.project or {}).get("name"),
            "model_name": (self.model or {}).get("name"),
            "n_sites": len(self.sites),
            "n_buildings": len(self.buildings),
            "n_storeys": len(self.storeys),
            "n_spaces": len(self.spaces),
            "n_zones": len(self.zones),
            "n_elements": len(self.elements),
            "elements_by_type_top": dict(
                sorted(
                    ((k, len(v)) for k, v in self.elements_by_type.items()),
                    key=lambda kv: kv[1],
                    reverse=True,
                )[:20]
            ),
        }


def extract_snapshot(client: BIMDataClient) -> ModelSnapshot:
    """Récupère le modèle complet depuis BIMData.

    Les routes BIMData retournent parfois 404 quand l'aspect n'est pas indexé
    par le moteur (modèle non finalisé, etc.) ; on tolère silencieusement ces
    erreurs pour produire un snapshot partiel.
    """
    def safe(fn, default):
        try:
            return fn()
        except Exception:
            return default

    snap = ModelSnapshot(
        project=safe(client.get_project, {}),
        model=safe(client.get_model, {}),
        sites=safe(client.get_sites, []),
        buildings=safe(client.get_buildings, []),
        storeys=safe(client.get_storeys, []),
        spaces=safe(client.get_spaces, []),
        zones=safe(client.get_zones, []),
        elements=safe(client.get_raw_elements, []),
        structure_tree=safe(client.get_structure_tree, []),
    )
    return snap.index()
