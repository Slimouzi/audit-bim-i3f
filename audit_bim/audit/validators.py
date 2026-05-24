"""Validation des **valeurs** des propriétés (vs simple présence/absence).

Pour chaque propriété d'un élément IFC dont la valeur est *présente*, on
vérifie qu'elle a bien la nature sémantique attendue (numérique positif,
booléen, chaîne non vide, coordonnée dans une plage…). Une valeur présente
mais incohérente est aussi grave qu'une valeur manquante — voire pire
puisqu'elle peut induire en erreur le BIM Manager qui consulte la maquette.

Heuristiques basées sur le **nom de la propriété** et accessoirement sur le
commentaire de la spec CCH (ex: « Champs : V / F » → booléen attendu).
Renvoie ``None`` si la valeur est valide, sinon une chaîne courte décrivant
le motif de l'invalidité (utilisée dans le finding).
"""
from __future__ import annotations

import re

# Noms (substrings, insensibles à la casse) suggérant une valeur numérique > 0.
_NUMERIC_POSITIVE_KEYS = (
    "surface", "area", "volume", "height", "width", "length", "depth",
    "thickness", "diameter", "épaisseur", "épaisseurs",
    "débit", "débits", "flowrate", "airflow",
    "puissance", "power", "wattage",
    "transmittance", "u-value", "u_value", "uvalue",
    "rating", "isolation", "resistance",
)

# Noms suggérant un booléen (V/F dans la spec CCH).
_BOOL_KEYS = (
    "isexternal", "loadbearing", "combustible", "compartimentage",
    "habitable", "annexe", "accessible", "extérieur",
    "porteur",
)

# Noms suggérant une chaîne non vide obligatoire (référence commerciale,
# fabricant, modèle, marque, code de gestion).
_ALPHANUM_REQUIRED_KEYS = (
    "reference", "référence", "fabricant", "manufacturer",
    "marque", "brand", "modèle", "model", "code", "tag", "mark",
)

# Bool admis en représentation chaîne (français + anglais)
_BOOL_STR_VALUES = {"V", "F", "TRUE", "FALSE", "OUI", "NON", "0", "1", "VRAI", "FAUX", "YES", "NO"}


def _has_key(text: str, keys: tuple[str, ...]) -> bool:
    t = (text or "").lower()
    return any(k in t for k in keys)


def _is_bool_value(value) -> bool:
    if isinstance(value, bool):
        return True
    if isinstance(value, (int, float)) and value in (0, 1):
        return True
    if isinstance(value, str):
        return value.strip().upper() in _BOOL_STR_VALUES
    return False


def _expects_bool(prop_name: str, comment: str | None) -> bool:
    if _has_key(prop_name, _BOOL_KEYS):
        return True
    if comment and re.search(r"\bv\s*/\s*f\b|\boui\s*/\s*non\b|true\s*/\s*false", comment, re.I):
        return True
    return False


def validate_property_value(
    value,
    *,
    property_name: str,
    pset_or_attribute: str | None = None,
    comment: str | None = None,
) -> str | None:
    """Renvoie ``None`` si ``value`` est valide pour la propriété, sinon une
    chaîne courte décrivant l'incohérence (utilisée dans le finding).

    Args:
        value: valeur réellement présente dans le modèle (non vide — la
            détection de l'absence est faite en amont).
        property_name: nom de la propriété (ex: ``"Surface"``,
            ``"IsExternal"``, ``"Référence commerciale"``).
        pset_or_attribute: Pset ou attribut porteur (info contextuelle).
        comment: commentaire de la ligne du CCH (peut mentionner « V/F »
            pour signaler un booléen).
    """
    if value is None:
        return None  # absence gérée ailleurs
    full_name = " ".join(filter(None, [pset_or_attribute or "", property_name or ""]))

    # 1. Numérique positif
    if _has_key(full_name, _NUMERIC_POSITIVE_KEYS):
        try:
            n = float(value)
        except (TypeError, ValueError):
            return f"valeur non numérique : {value!r}"
        if n < 0:
            return f"valeur négative ({n}) — attendu ≥ 0"
        # surface/volume nuls = très probablement une erreur (élément vide)
        if n == 0 and _has_key(property_name, ("surface", "area", "volume")):
            return "valeur nulle (élément géométriquement vide ?)"
        return None

    # 2. Booléen attendu
    if _expects_bool(property_name, comment):
        if _is_bool_value(value):
            return None
        return f"valeur non booléenne : {value!r} (attendu V/F)"

    # 3. Chaîne alphanumérique non vide (référence, fabricant, etc.)
    if _has_key(property_name, _ALPHANUM_REQUIRED_KEYS):
        if isinstance(value, str):
            s = value.strip()
            if not s:
                return "chaîne vide après suppression des espaces"
            if len(s) < 2:
                return f"chaîne anormalement courte : {value!r}"
            return None
        # Un Tag/Mark numérique reste acceptable
        if isinstance(value, (int, float)):
            return None
        return f"type inattendu pour identifiant : {type(value).__name__}"

    # 4. Coordonnées géographiques (depuis IfcSite)
    if "latitude" in property_name.lower():
        try:
            n = float(value)
        except (TypeError, ValueError):
            return f"latitude non numérique : {value!r}"
        if not -90.0 <= n <= 90.0:
            return f"latitude hors plage [-90, 90] : {n}"
        return None
    if "longitude" in property_name.lower():
        try:
            n = float(value)
        except (TypeError, ValueError):
            return f"longitude non numérique : {value!r}"
        if not -180.0 <= n <= 180.0:
            return f"longitude hors plage [-180, 180] : {n}"
        return None

    return None  # aucune validation spécifique — on accepte
