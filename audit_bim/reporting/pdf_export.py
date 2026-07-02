"""Conversion .docx → .pdf **best-effort** (livrables consolidés).

Utilise LibreOffice headless (``soffice``) s'il est présent sur la machine.
Absent → renvoie ``None`` : le ``.docx`` reste le livrable, **aucun échec
dur**. Le binaire est overridable via ``AUDIT_BIM_SOFFICE``.

Aucune dépendance Python nouvelle : on invoque le binaire système.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


def _soffice_bin() -> str | None:
    override = os.getenv("AUDIT_BIM_SOFFICE")
    if override and Path(override).exists():
        return override
    for name in ("soffice", "libreoffice"):
        found = shutil.which(name)
        if found:
            return found
    return None


def docx_to_pdf(docx_path: str | Path, *, timeout: int = 120) -> Path | None:
    """Convertit ``docx_path`` en PDF (même dossier). ``None`` si LibreOffice
    est absent ou si la conversion échoue (le .docx reste valide)."""
    docx_path = Path(docx_path)
    soffice = _soffice_bin()
    if soffice is None or not docx_path.is_file():
        return None
    out_dir = docx_path.parent
    try:
        subprocess.run(
            [
                soffice,
                "--headless",
                "--convert-to",
                "pdf",
                "--outdir",
                str(out_dir),
                str(docx_path),
            ],
            check=True,
            capture_output=True,
            timeout=timeout,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    pdf = docx_path.with_suffix(".pdf")
    return pdf if pdf.is_file() else None
