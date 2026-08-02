"""Accès **direct** au calcul géométrique (IfcOpenShell), sans passer par MCP.

Le calcul vit dans ``ifc-geometry`` sous forme de **fonctions Python pures** :
``export_computed_quantities`` et ``envelope.run`` ne dépendent ni de FastMCP ni
d'un serveur — seulement d'``ifcopenshell`` et des contrats ``bim-core``. On les
importe donc directement.

Pourquoi pas un appel MCP → MCP : cela dépendrait du harnais (tools énumérés à
l'ouverture d'une conversation, serveur chargé au démarrage), donc d'un contexte
que le produit ne contrôle pas. Un import Python est déterministe et testable.

Le backend est une **dépendance optionnelle** (extra ``geometry``) : ifcopenshell
est lourd et tous les déploiements d'audit-bim n'en ont pas besoin. Son absence
n'est jamais une erreur silencieuse — elle produit un message qui nomme ce qui
manque et comment l'installer.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

BACKEND_DISTRIBUTION = "ifc-geometry-mcp"
#: Extra à installer pour activer le calcul géométrique local.
BACKEND_EXTRA = "geometry"
BACKEND_INSTALL = f"pip install 'audit-bim-i3f[{BACKEND_EXTRA}]'"


class GeometryBackendUnavailable(RuntimeError):
    """Le calcul géométrique local n'est pas installé.

    Message actionnable : l'appelant doit soit installer l'extra, soit fournir
    lui-même le JSON de contrat déjà calculé.
    """

    def __init__(self, cause: Exception | None = None):
        self.cause = cause
        super().__init__(
            "Calcul géométrique indisponible : le backend "
            f"``{BACKEND_DISTRIBUTION}`` n'est pas installé dans cet "
            f"environnement. Installer via ``{BACKEND_INSTALL}``, ou fournir "
            "directement ``computed_quantities_json`` / ``envelope_json`` "
            "produits par le MCP ifc-geometry."
        )


def backend_available() -> bool:
    """Le calcul géométrique local est-il utilisable ?"""
    try:
        _load()
    except GeometryBackendUnavailable:
        return False
    return True


def _load():
    """Importe les fonctions de calcul (import paresseux, jamais au module)."""
    try:
        from ifc_openshell_mcp import ifc_utils
        from ifc_openshell_mcp.analyzers import envelope
        from ifc_openshell_mcp.enrichers import base_quantities
    except ImportError as exc:  # backend absent ou cassé
        raise GeometryBackendUnavailable(exc) from exc
    return ifc_utils, envelope, base_quantities


def compute_quantities_payload(ifc_path: str | Path) -> dict[str, Any]:
    """Calcule le contrat ``computed_base_quantities/v1`` depuis un .ifc.

    Ne touche **jamais** au fichier IFC : le calcul est en lecture seule.
    """
    ifc_utils, _envelope, base_quantities = _load()
    model = ifc_utils.open_model(str(ifc_path))
    return base_quantities.export_computed_quantities(model, ifc_file=str(ifc_path))


def compute_envelope_payload(
    ifc_path: str | Path,
    *,
    seuil_3f: float | None = None,
    layer_pattern: str | None = None,
    type_pattern: str | None = None,
) -> dict[str, Any]:
    """Calcule le contrat ``envelope_quantities/v1`` depuis un .ifc."""
    ifc_utils, envelope, _bq = _load()
    model = ifc_utils.open_model(str(ifc_path))
    return envelope.run(
        model,
        file_name=Path(ifc_path).name,
        seuil_3f=seuil_3f,
        layer_pattern=layer_pattern,
        type_pattern=type_pattern,
    )


__all__ = [
    "BACKEND_DISTRIBUTION",
    "BACKEND_EXTRA",
    "BACKEND_INSTALL",
    "GeometryBackendUnavailable",
    "backend_available",
    "compute_envelope_payload",
    "compute_quantities_payload",
]
