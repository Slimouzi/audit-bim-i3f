"""Sandbox des chemins d'écriture / lecture exposés via MCP.

Un serveur MCP en mode HTTP peut être piloté par un agent LLM
distant : un ``output_path`` ou un ``doe_path`` mal formé (ou
volontairement hostile) doit être refusé avant que python ne touche
au disque.

Deux familles de validation :

- :func:`safe_export_path` — toute écriture (xlsx, docx, json, cache)
  doit rester sous ``AUDIT_OUTPUT_DIR`` (défaut ``./out``), sans
  ``..``, sans écrasement silencieux.
- :func:`safe_input_path` — toute lecture pilotée par un client MCP
  (DOE xlsx/pdf, CCH PDF, fichiers tiers) doit rester sous
  ``AUDIT_INPUT_DIR`` si la variable est définie. Si l'env n'est pas
  fixée, on accepte n'importe quel chemin existant (mode dev/CLI :
  l'utilisateur sait ce qu'il fait). Une taille max et une whitelist
  d'extensions sont appliquées dans tous les cas.

Toutes les violations lèvent :class:`UnsafePathError` (sous-classe
de ``ValueError``).
"""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_EXPORT_DIR = "./out"
DEFAULT_MAX_INPUT_MB = 50

# Extensions acceptées en *input* (DOE / CCH / annexes). Volontairement
# strict : pas de .zip, .exe, .py, .so, etc.
ALLOWED_INPUT_EXTENSIONS = {
    ".pdf",
    ".xlsx",
    ".xlsm",
    ".xls",
    ".docx",
    ".csv",
    ".json",
    ".png",
    ".jpg",
    ".jpeg",
    ".tif",
    ".tiff",
    ".bmp",
}


class UnsafePathError(ValueError):
    """Chemin refusé par la sandbox d'I/O."""


# ── Écriture ─────────────────────────────────────────────────────────────


def get_export_root() -> Path:
    """Racine d'export courante (résolue, créée si absente).

    Lue à chaque appel pour permettre aux tests de surcharger
    ``AUDIT_OUTPUT_DIR`` via ``monkeypatch.setenv``.
    """
    root_str = os.getenv("AUDIT_OUTPUT_DIR") or DEFAULT_EXPORT_DIR
    root = Path(root_str).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def safe_export_path(
    output_path: str | os.PathLike,
    *,
    overwrite: bool = False,
    export_root: Path | None = None,
) -> Path:
    """Valide et résout un chemin d'écriture sous la racine d'export.

    Args:
        output_path: Chemin demandé. Relatif → résolu sous la racine.
            Absolu → doit être contenu dans la racine.
        overwrite: Si ``False`` (défaut) et fichier existant, refuse.
        export_root: Override pour les tests.

    Returns:
        ``Path`` absolu, parents créés.

    Raises:
        UnsafePathError: ``..``, évasion de racine, ou écrasement non
            autorisé.
    """
    root = (export_root or get_export_root()).resolve()
    raw = Path(output_path).expanduser()

    if any(part == ".." for part in raw.parts):
        raise UnsafePathError(f"Composants `..` interdits dans le chemin : {output_path!r}")

    candidate = raw.resolve() if raw.is_absolute() else (root / raw).resolve()

    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise UnsafePathError(f"Le chemin doit rester sous {root}. Reçu : {candidate}") from exc

    if candidate.exists() and not overwrite:
        raise UnsafePathError(f"{candidate} existe déjà — passer `overwrite=True` pour l'écraser.")

    candidate.parent.mkdir(parents=True, exist_ok=True)
    return candidate


def safe_export_dir(
    dir_path: str | os.PathLike,
    *,
    export_root: Path | None = None,
) -> Path:
    """Variante de :func:`safe_export_path` pour un **dossier** (cache,
    sous-arborescence d'export).

    Pas de garde-fou d'écrasement (on ne « crée » pas un dossier au sens
    où on remplacerait un fichier existant). Le dossier est créé si
    absent.

    Raises:
        UnsafePathError: ``..`` ou évasion de la racine.
    """
    root = (export_root or get_export_root()).resolve()
    raw = Path(dir_path).expanduser()

    if any(part == ".." for part in raw.parts):
        raise UnsafePathError(f"Composants `..` interdits dans le chemin : {dir_path!r}")

    candidate = raw.resolve() if raw.is_absolute() else (root / raw).resolve()

    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise UnsafePathError(f"Le dossier doit rester sous {root}. Reçu : {candidate}") from exc

    candidate.mkdir(parents=True, exist_ok=True)
    return candidate


# ── Lecture ──────────────────────────────────────────────────────────────


def _input_root() -> Path | None:
    """Racine d'inputs autorisée. ``None`` si ``AUDIT_INPUT_DIR`` n'est pas
    défini (mode permissif : utile en CLI / Claude Desktop local)."""
    root_str = os.getenv("AUDIT_INPUT_DIR")
    if not root_str:
        return None
    return Path(root_str).expanduser().resolve()


def _max_input_bytes() -> int:
    """Taille maximale acceptée pour un fichier d'input (octets)."""
    raw = os.getenv("AUDIT_MAX_INPUT_MB")
    try:
        mb = int(raw) if raw else DEFAULT_MAX_INPUT_MB
    except ValueError:
        mb = DEFAULT_MAX_INPUT_MB
    return max(1, mb) * 1024 * 1024


def safe_input_path(
    input_path: str | os.PathLike,
    *,
    allowed_extensions: set[str] | None = None,
) -> Path:
    """Valide un chemin de lecture exposé via un tool MCP.

    Règles appliquées :

    1. ``..`` interdits dans le chemin brut.
    2. Si ``AUDIT_INPUT_DIR`` est défini, le chemin résolu doit rester
       sous cette racine.
    3. Extension dans la whitelist (``ALLOWED_INPUT_EXTENSIONS`` par
       défaut, surchargable).
    4. Fichier existant ET régulier.
    5. Taille ≤ ``AUDIT_MAX_INPUT_MB`` (défaut 50 MB).

    Args:
        input_path: Chemin demandé.
        allowed_extensions: Whitelist d'extensions (en minuscule, avec
            le point — ex ``{".pdf", ".xlsx"}``). ``None`` →
            :data:`ALLOWED_INPUT_EXTENSIONS`.

    Returns:
        ``Path`` absolu validé.

    Raises:
        UnsafePathError: violation d'une des règles ci-dessus.
        FileNotFoundError: fichier inexistant.
    """
    raw = Path(input_path).expanduser()
    if any(part == ".." for part in raw.parts):
        raise UnsafePathError(f"Composants `..` interdits : {input_path!r}")

    candidate = raw.resolve()

    root = _input_root()
    if root is not None:
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise UnsafePathError(
                f"Le chemin doit rester sous AUDIT_INPUT_DIR={root}. Reçu : {candidate}"
            ) from exc

    extensions = allowed_extensions or ALLOWED_INPUT_EXTENSIONS
    if candidate.suffix.lower() not in extensions:
        raise UnsafePathError(
            f"Extension {candidate.suffix!r} non autorisée. Autorisées : {sorted(extensions)}"
        )

    if not candidate.exists():
        raise FileNotFoundError(candidate)
    if not candidate.is_file():
        raise UnsafePathError(f"Le chemin n'est pas un fichier régulier : {candidate}")

    size = candidate.stat().st_size
    max_bytes = _max_input_bytes()
    if size > max_bytes:
        raise UnsafePathError(
            f"Fichier trop volumineux : {size} octets > limite {max_bytes} (AUDIT_MAX_INPUT_MB)."
        )

    return candidate
