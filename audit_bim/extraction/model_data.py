"""Snapshot du modèle IFC nécessaire à l'audit.

L'audit n'exige qu'une vision *par classe IFC* + hiérarchie spatiale + Psets ;
on encapsule tout dans une structure ``ModelSnapshot`` immuable.
"""

from __future__ import annotations

# ``ModelSnapshot`` (le type de contrat) vit désormais dans ``bim-core``.
# On le ré-exporte ici pour préserver les imports historiques
# (``from audit_bim.extraction.model_data import ModelSnapshot``). Seule la
# fonction d'extraction ``extract_snapshot`` — couplée au client BIMData —
# reste dans ce MCP.
from bim_core.model_snapshot import ModelSnapshot

from .client import BIMDataClient

__all__ = ["ModelSnapshot", "extract_snapshot"]


def extract_snapshot(client: BIMDataClient) -> ModelSnapshot:
    """Récupère le modèle complet depuis BIMData.

    Les routes BIMData retournent parfois 404 quand l'aspect n'est pas indexé
    par le moteur (modèle non finalisé, etc.) ; on tolère ces erreurs pour
    produire un snapshot partiel — mais on les *journalise* sur stderr pour
    qu'un snapshot vide ne soit pas confondu avec un modèle vide.
    """
    import sys

    errors: list[str] = []

    def safe(label, fn, default):
        try:
            return fn()
        except Exception as e:
            errors.append(f"{label}: {type(e).__name__}: {e}")
            return default

    snap = ModelSnapshot(
        project=safe("get_project", client.get_project, {}),
        model=safe("get_model", client.get_model, {}),
        sites=safe("get_sites", client.get_sites, []),
        buildings=safe("get_buildings", client.get_buildings, []),
        storeys=safe("get_storeys", client.get_storeys, []),
        spaces=safe("get_spaces", client.get_spaces, []),
        zones=safe("get_zones", client.get_zones, []),
        elements=safe("get_raw_elements", client.get_raw_elements, []),
        structure_tree=safe("get_structure_tree", client.get_structure_tree, []),
    )
    if errors:
        print(
            f"⚠ extract_snapshot: {len(errors)} route(s) BIMData en erreur :",
            file=sys.stderr,
        )
        for msg in errors:
            print(f"   • {msg}", file=sys.stderr)
    return snap.index()
