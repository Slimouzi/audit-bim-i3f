"""Ré-export : sandbox de chemins I/O (``bim_core.paths``, profil **audit**).

L'implémentation vit dans ``bim-core`` (module :mod:`bim_core.paths`, deux
profils historiques). Elle transitait auparavant par le package
``bim-sandbox``, désormais décommissionné : l'import est repointé vers la
source, sans passer par le shim. Ce module ré-exporte le profil **audit**
derrière les chemins et signatures historiques
(``from audit_bim.safe_paths import safe_input_path, …``) — aucun call-site à
réécrire, comportement et erreurs observables inchangés.

Les écritures (``safe_export_path`` / ``safe_export_read_path`` /
``safe_export_dir`` / ``get_export_root``) et les constantes
(``ALLOWED_INPUT_EXTENSIONS``, ``DEFAULT_*``) sont les objets de
``bim_core.paths`` tels quels. Seul ``safe_input_path`` est un mince wrapper qui
fixe ``profile="audit"`` pour préserver la signature publique côté audit-bim.
"""

from __future__ import annotations

import os
from pathlib import Path

from bim_core.paths import (
    ALLOWED_INPUT_EXTENSIONS,
    DEFAULT_EXPORT_DIR,
    DEFAULT_MAX_INPUT_MB,
    UnsafePathError,
    get_export_root,
    safe_export_dir,
    safe_export_path,
    safe_export_read_path,
)
from bim_core.paths import safe_input_path as _core_safe_input_path

__all__ = [
    "UnsafePathError",
    "safe_input_path",
    "safe_export_path",
    "safe_export_read_path",
    "safe_export_dir",
    "get_export_root",
    "ALLOWED_INPUT_EXTENSIONS",
    "DEFAULT_EXPORT_DIR",
    "DEFAULT_MAX_INPUT_MB",
]


def safe_input_path(
    input_path: str | os.PathLike,
    *,
    allowed_extensions: set[str] | None = None,
) -> Path:
    """Valide un chemin de lecture exposé via un tool MCP (profil **audit**).

    Signature publique historique préservée. Délègue au profil audit de
    ``bim_core.paths`` : ``..`` interdits → résolution cwd → confinement sous
    ``AUDIT_INPUT_DIR`` → whitelist (``ALLOWED_INPUT_EXTENSIONS`` par défaut) →
    existence → fichier régulier → taille ≤ ``AUDIT_MAX_INPUT_MB``.
    """
    return _core_safe_input_path(input_path, profile="audit", allowed_extensions=allowed_extensions)
