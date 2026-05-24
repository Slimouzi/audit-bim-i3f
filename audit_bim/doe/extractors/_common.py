"""Helpers partagés par les extracteurs DOE (Excel, PDF, OCR).

Centralise la convention d'en-têtes et la transformation d'une *ligne
tabulaire* (séquence de cellules) en :class:`audit_bim.doe.models.DoeRecord`.
Garantit que tous les extracteurs produisent des records cohérents,
quelle que soit la source (xlsx, PDF natif, OCR).
"""

from __future__ import annotations

import re
import unicodedata

from ..models import DoeRecord

# Mapping en-têtes connues — insensible à la casse, accent-tolérant.
# Chaque slot est mappé à un champ dédié de ``DoeRecord``.
_HEADER_ALIASES: dict[str, tuple[str, ...]] = {
    "uuid": ("uuid", "globalid", "global id", "ifc guid", "ifcguid"),
    "tag": ("tag", "mark", "numero", "numéro", "code", "identifiant"),
    "name": (
        "nom",
        "libelle",
        "libellé",
        "designation",
        "désignation",
        "name",
    ),
    "type": ("type", "categorie", "catégorie", "famille"),
    "storey": ("etage", "étage", "niveau", "storey", "level"),
    "zone": ("zone", "local", "piece", "pièce", "logement", "room"),
}

DEFAULT_PSET = "Pset_DOE"


def normalize_header_text(s: str) -> str:
    """Normalise une chaîne d'en-tête pour matching d'alias.

    Retire accents, espaces de bord, met en minuscules.

    Args:
        s: Chaîne brute (peut contenir accents, casse mixte).

    Returns:
        Forme canonique pour comparaison directe aux alias.
    """
    nfkd = unicodedata.normalize("NFKD", s or "")
    no_accents = "".join(c for c in nfkd if not unicodedata.combining(c))
    return no_accents.strip().lower()


def detect_header(value) -> tuple[str | None, tuple[str, str] | None]:
    """Identifie la sémantique d'une cellule d'en-tête.

    Args:
        value: Contenu brut de la cellule.

    Returns:
        Tuple ``(slot, pset_prop)`` où :

        - ``slot`` (str) si la cellule désigne un champ connu de
          ``DoeRecord`` (``"uuid"`` / ``"tag"`` / ``"name"`` / ``"type"``
          / ``"storey"`` / ``"zone"``).
        - ``pset_prop`` ``(pset, prop)`` si la cellule désigne une
          propriété : convention ``Pset.Propriete`` ou ``Pset/Propriete``,
          sinon défaut ``("Pset_DOE", <texte>)``.
        - Les deux à ``None`` si la cellule est vide.
    """
    if value is None:
        return None, None
    text = str(value).strip()
    if not text:
        return None, None
    norm = normalize_header_text(text)
    for slot, aliases in _HEADER_ALIASES.items():
        if norm in aliases:
            return slot, None
    # Convention Pset.prop ou Pset/prop
    m = re.match(r"^([A-Za-z][A-Za-z0-9_]+)\s*[./]\s*(.+)$", text)
    if m:
        return None, (m.group(1).strip(), m.group(2).strip())
    return None, (DEFAULT_PSET, text)


def row_to_record(
    headers: list,
    row: list,
    col_map: list[tuple[str | None, tuple[str, str] | None]],
    *,
    source: str,
    row_index: int,
) -> DoeRecord | None:
    """Convertit une ligne tabulaire en ``DoeRecord``.

    Args:
        headers: Cellules d'en-tête de la table (pour ``raw_row``).
        row: Cellules de la ligne courante.
        col_map: Mapping par colonne, issu de ``detect_header`` appliqué
            sur ``headers``.
        source: Chemin (ou identifiant) du fichier source.
        row_index: Numéro 1-indexé de la ligne dans le document.

    Returns:
        ``DoeRecord`` si la ligne porte au moins un identifiant (uuid,
        tag, name) **et** au moins une propriété. ``None`` sinon (ligne
        filtrée par souci de qualité du matching aval).
    """
    if not any(c not in (None, "") for c in row):
        return None

    rec = DoeRecord(
        source=source,
        row_index=row_index,
        properties={},
        raw_row={
            str(h or f"col{i}"): row[i] if i < len(row) else None for i, h in enumerate(headers)
        },
    )
    for col_i, (slot, pset_prop) in enumerate(col_map):
        val = row[col_i] if col_i < len(row) else None
        if val in (None, ""):
            continue
        if slot == "uuid":
            rec.uuid_hint = str(val).strip()
        elif slot == "tag":
            rec.tag_hint = str(val).strip()
        elif slot == "name":
            rec.name_hint = str(val).strip()
        elif slot == "type":
            rec.type_hint = str(val).strip()
        elif slot == "storey":
            rec.storey_hint = str(val).strip()
        elif slot == "zone":
            rec.zone_hint = str(val).strip()
        elif pset_prop:
            pset, prop = pset_prop
            rec.properties.setdefault(pset, {})[prop] = val

    if not (rec.uuid_hint or rec.tag_hint or rec.name_hint):
        return None
    if not rec.properties:
        return None
    return rec


def find_header_row(rows: list[list], max_scan: int = 10) -> int | None:
    """Repère la première ligne d'en-tête plausible dans une table.

    Heuristique simple : première ligne (parmi les ``max_scan`` premières)
    ayant **au moins 2 cellules non vides**.

    Args:
        rows: Lignes de la table (liste de séquences).
        max_scan: Nombre max de lignes à scanner depuis le début.

    Returns:
        Index 0-indexé de la ligne d'en-tête, ou ``None`` si aucune
        candidate n'est trouvée.
    """
    for i, row in enumerate(rows[:max_scan]):
        non_empty = sum(1 for c in row if c not in (None, ""))
        if non_empty >= 2:
            return i
    return None
