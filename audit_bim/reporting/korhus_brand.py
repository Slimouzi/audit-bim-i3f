"""Résolution des assets de la charte Korhus.ai.

Le brand kit est livré comme un dossier autonome (logos, tokens,
template Word de référence). Les rapports d'audit le référencent en
*runtime* — pas de copie dans le package — pour qu'une mise à jour de
la charte ne nécessite pas un nouveau release de ``audit-bim-i3f``.

Résolution du chemin (premier match) :

1. Variable d'environnement ``KORHUS_BRAND_KIT_DIR`` si définie et
   pointant vers un dossier existant. **Mode recommandé** — explicite,
   portable, testable.
2. Sous-dossier ``korhus_brand_kit/`` voisin du repo audit-bim-i3f
   (sibling de la racine du package). Fallback de confort pour un
   workflow local où le brand kit est cloné à côté.

Le module reste **silencieux** quand le brand kit n'est pas
disponible : la génération de rapport ne doit pas planter sur un poste
de CI sans assets, elle dégrade gracieusement (wordmark texte à la
place du logo).
"""

from __future__ import annotations

import os
from pathlib import Path

# Variantes de logo, mappées vers leur nom de fichier dans assets/.
# Sémantique : ``primary`` pour fonds clairs, ``light`` (inversé blanc)
# pour fonds sombres — la couverture sombre du rapport utilise donc
# ``light``.
_LOGO_FILES: dict[str, str] = {
    "primary": "korhus_logo_primary_wordmark.png",
    "dark": "korhus_logo_dark_wordmark.png",
    "light": "korhus_logo_reversed_or_light_wordmark.png",
    "mark_primary": "korhus_mark_primary.png",
    "mark_dark": "korhus_mark_mono_dark.png",
    "mark_light": "korhus_mark_light.png",
}


def find_brand_kit_dir() -> Path | None:
    """Renvoie le dossier racine du brand kit Korhus ou ``None``.

    L'ordre de résolution suit la docstring du module. Aucun side
    effect ; ne lève pas. Un caller qui *exige* le brand kit doit
    vérifier le retour et lever lui-même.
    """
    env = os.getenv("KORHUS_BRAND_KIT_DIR")
    if env:
        p = Path(env).expanduser()
        if p.is_dir():
            return p

    # Sibling du repo audit-bim-i3f (utile pour les setups locaux où le
    # brand kit est cloné à côté). On remonte depuis l'emplacement de
    # ce fichier jusqu'à trouver un voisin nommé ``korhus_brand_kit``.
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent.parent / "korhus_brand_kit"
        if candidate.is_dir():
            return candidate

    return None


def find_logo(variant: str = "light") -> Path | None:
    """Renvoie le chemin d'un fichier de logo Korhus, ou ``None``.

    Args:
        variant: clé parmi ``primary | dark | light | mark_primary |
            mark_dark | mark_light``. Défaut ``"light"`` (inversé,
            adapté à la couverture sombre du rapport).

    Returns:
        ``Path`` absolu du fichier, ou ``None`` si le brand kit n'est
        pas trouvé / la variante demandée n'existe pas sur disque.
    """
    if variant not in _LOGO_FILES:
        raise ValueError(
            f"Variante logo inconnue : {variant!r}. Valeurs admises : {sorted(_LOGO_FILES)}"
        )
    root = find_brand_kit_dir()
    if root is None:
        return None
    path = root / "assets" / _LOGO_FILES[variant]
    return path if path.is_file() else None
