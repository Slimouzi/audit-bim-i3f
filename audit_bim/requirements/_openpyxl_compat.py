"""Monkey-patches défensifs sur openpyxl pour absorber les fichiers I3F.

Les xlsx du CCH I3F contiennent des ``CustomFilter`` dont la valeur ne respecte
pas la validation stricte d'openpyxl (« Value must be either numerical or a
string containing a wildcard »). Cela fait échouer la lecture *complète* du
classeur, même en mode streaming.

On patche le descripteur ``CustomFilter.val`` pour qu'il accepte n'importe
quelle chaîne — ce qui n'a pas d'incidence pour nous puisqu'on n'utilise pas
les filtres, on lit juste les cellules.
"""

from __future__ import annotations

_PATCHED = False


def patch_openpyxl() -> None:
    """Idempotent — applique le patch une seule fois par process."""
    global _PATCHED
    if _PATCHED:
        return
    try:
        from openpyxl.descriptors.base import String
        from openpyxl.worksheet import filters as flt

        flt.CustomFilter.val = String(allow_none=True)
    except Exception:
        # Si l'API d'openpyxl change un jour, on ne casse pas l'audit pour
        # autant : la lecture peut soit fonctionner d'elle-même soit lever
        # l'erreur originale, ce qui sera explicite dans les logs.
        pass
    _PATCHED = True
