"""Résolution des assets de la charte BIMData.

Le brand kit (logos, tokens) est référencé en *runtime* — pas de copie
dans le package — pour qu'une mise à jour de la charte ne nécessite pas
un nouveau release de ``audit-bim-i3f``.

Résolution d'un logo (``find_logo``), premier match :

1. Brand kit structuré ``<root>/assets/<nom de fichier par variante>``,
   ``<root>`` étant résolu par :func:`find_brand_kit_dir` (variable
   d'env ``BIMDATA_BRAND_KIT_DIR`` / ``KORHUS_BRAND_KIT_DIR`` puis
   dossier sibling ``bimdata_brand_kit/`` / ``korhus_brand_kit/``).
2. **Logo « vrac »** : première image raster valide trouvée dans un
   dossier sibling ``Logo_BIMData/`` (ou ``logo_bimdata/``). Pratique
   quand on dépose simplement un fichier logo à côté du repo, sans
   structure ``assets/``.

Validation : seuls les fichiers dont les octets magiques correspondent
à un PNG ou un JPEG réel sont retenus. Les fichiers AppleDouble macOS
(métadonnées sans données d'image, ``00 05 16 07``) sont ignorés — un
tel fichier ferait échouer ``add_picture`` côté Word.

Le module reste **silencieux** quand aucun logo n'est disponible : la
génération de rapport ne doit pas planter sur un poste de CI sans
assets, elle dégrade gracieusement (wordmark texte « BIMDATA » à la
place du logo).
"""

from __future__ import annotations

import os
from pathlib import Path

# Wordmark texte de repli quand aucun logo image n'est résolu.
WORDMARK = "BIMDATA"

# Dossiers sibling où un logo peut être déposé « en vrac » (un seul
# fichier image, sans structure ``assets/``).
_LOOSE_LOGO_DIRNAMES = ("Logo_BIMData", "logo_bimdata")
# Extensions raster embarquables dans un .docx (svg non supporté).
_RASTER_EXTS = (".png", ".jpg", ".jpeg")

# Variantes de logo, mappées vers leur nom de fichier dans assets/.
# Sémantique : ``primary`` pour fonds clairs, ``light`` (inversé blanc)
# pour fonds sombres — la couverture sombre du rapport utilise ``light``.
_LOGO_FILES: dict[str, str] = {
    "primary": "bimdata_logo_primary.png",
    "dark": "bimdata_logo_dark.png",
    "light": "bimdata_logo_white.png",
    "mark_primary": "bimdata_mark_primary.png",
    "mark_dark": "bimdata_mark_dark.png",
    "mark_light": "bimdata_mark_light.png",
}

# Dossiers brand kit candidats (le premier nom est le canonique BIMData).
_BRAND_KIT_DIRNAMES = ("bimdata_brand_kit", "korhus_brand_kit")
# Variables d'environnement candidates (canonique d'abord).
_BRAND_KIT_ENV_VARS = ("BIMDATA_BRAND_KIT_DIR", "KORHUS_BRAND_KIT_DIR")


def find_brand_kit_dir() -> Path | None:
    """Renvoie le dossier racine du brand kit BIMData ou ``None``.

    L'ordre de résolution suit la docstring du module. Aucun side
    effect ; ne lève pas. Un caller qui *exige* le brand kit doit
    vérifier le retour et lever lui-même.
    """
    for env_var in _BRAND_KIT_ENV_VARS:
        env = os.getenv(env_var)
        if env:
            p = Path(env).expanduser()
            if p.is_dir():
                return p

    # Sibling du repo (utile pour les setups locaux où le brand kit est
    # cloné à côté). On remonte depuis l'emplacement de ce fichier.
    here = Path(__file__).resolve()
    for parent in here.parents:
        for dirname in _BRAND_KIT_DIRNAMES:
            candidate = parent.parent / dirname
            if candidate.is_dir():
                return candidate

    return None


def _is_raster_image(path: Path) -> bool:
    """Vrai si ``path`` est un PNG ou JPEG réel (vérif. octets magiques).

    Filtre les fichiers AppleDouble macOS (``00 05 16 07``) et autres
    pseudo-images qui feraient échouer ``add_picture`` côté python-docx.
    """
    try:
        with path.open("rb") as fh:
            head = fh.read(4)
    except OSError:
        return False
    # PNG : 89 50 4E 47 ; JPEG : FF D8 FF
    return head.startswith(b"\x89PNG") or head.startswith(b"\xff\xd8\xff")


def _first_valid_raster(folder: Path) -> Path | None:
    """Première image raster valide (ordre alphabétique) d'un dossier.

    Ne retient que les fichiers PNG/JPEG réellement décodables
    (cf. :func:`_is_raster_image`). ``None`` si le dossier n'existe pas
    ou ne contient aucune image exploitable.
    """
    if not folder.is_dir():
        return None
    candidates = sorted(
        p for p in folder.iterdir() if p.suffix.lower() in _RASTER_EXTS and _is_raster_image(p)
    )
    return candidates[0] if candidates else None


def _find_loose_logo() -> Path | None:
    """Première image raster valide dans un dossier sibling ``Logo_BIMData/``.

    Permet de déposer un simple fichier logo à côté du repo sans monter
    une structure ``assets/``. Ne retient que les images réellement
    décodables (cf. :func:`_is_raster_image`).
    """
    here = Path(__file__).resolve()
    for parent in here.parents:
        for dirname in _LOOSE_LOGO_DIRNAMES:
            found = _first_valid_raster(parent.parent / dirname)
            if found is not None:
                return found
    return None


def find_logo(variant: str = "light") -> Path | None:
    """Renvoie le chemin d'un fichier de logo BIMData, ou ``None``.

    Args:
        variant: clé parmi ``primary | dark | light | mark_primary |
            mark_dark | mark_light``. Défaut ``"light"`` (inversé,
            adapté à la couverture sombre du rapport).

    Returns:
        ``Path`` absolu du fichier (brand kit structuré en priorité,
        sinon logo « vrac » sibling), ou ``None`` si aucun logo valide
        n'est trouvé.
    """
    if variant not in _LOGO_FILES:
        raise ValueError(
            f"Variante logo inconnue : {variant!r}. Valeurs admises : {sorted(_LOGO_FILES)}"
        )
    root = find_brand_kit_dir()
    if root is not None:
        path = root / "assets" / _LOGO_FILES[variant]
        if path.is_file():
            return path
    # Fallback : logo déposé « en vrac » dans un sibling Logo_BIMData/.
    return _find_loose_logo()
