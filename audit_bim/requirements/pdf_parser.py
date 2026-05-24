"""Parseur du PDF « Cahier des annexes CCH Bim I3F ».

Le PDF reprend (avec un peu plus de contexte rédactionnel) les mêmes annexes
que les xlsx. Il sert ici de :

1. Source de **version du CCH** (lue dans les premières pages : « Version 3.6 »).
2. Source de **secours** quand une annexe xlsx n'est pas fournie : on extrait
   alors la liste des étages, des types de zones et des noms de pièces depuis
   le texte du PDF.

L'extraction est volontairement *défensive* : si pypdf échoue ou que le PDF
n'expose pas le texte (scan), on renvoie un catalogue vide et l'audit fonctionne
quand même avec les exigences extraites des xlsx.
"""

from __future__ import annotations

import re
from pathlib import Path

try:
    from pypdf import PdfReader  # type: ignore
except Exception:  # pragma: no cover
    PdfReader = None  # type: ignore

from .models import RoomSpec, StoreyName, ZoneSpec

VERSION_RE = re.compile(r"Version\s*(\d+(?:[.,]\d+)?)", re.IGNORECASE)
STOREY_RE = re.compile(
    r"^(?P<n>"
    r"\d{1,2}[EÈ]ME\s+SOUS-SOL"
    r"|1ER\s+SOUS-SOL"
    r"|REZ-DE-CHAUSSEE|REZ-DE-JARDIN"
    r"|ENTRESOL(?:\s+\d{1,2})?"
    r"|1ER\s+ETAGE"
    r"|\d{1,2}[EÈ]ME\s+ETAGE"
    r"|COMBLES|TOITURE(?:\s+\d{1,2})?"
    r")\s*$",
    re.IGNORECASE,
)
ZONE_TYPE_RE = re.compile(r"^Zone\s+[A-Za-zéèîïô0-9' ]+$")
ROOM_LINE_RE = re.compile(
    r"^(?P<name>[A-ZÉÈÀÊ' \-]{3,30})\s{2,}(?P<type>[A-Za-zéèîïô \-]{3,30})\s+(?P<loc>PP|PC)\b"
)


def parse_pdf(pdf_path: str | Path) -> dict:
    """Extrait le minimum utile du PDF CCH.

    Returns:
        Dict ``{cch_version, storey_names, zone_specs, room_specs, full_text}``.
        Les listes peuvent être vides en cas d'extraction défensive.
    """
    pdf_path = Path(pdf_path)
    result = {
        "cch_version": None,
        "storey_names": [],
        "zone_specs": [],
        "room_specs": [],
    }
    if PdfReader is None or not pdf_path.exists():
        return result

    try:
        reader = PdfReader(str(pdf_path))
    except Exception:
        return result

    text_parts: list[str] = []
    for page in reader.pages:
        try:
            text_parts.append(page.extract_text() or "")
        except Exception:
            text_parts.append("")
    full_text = "\n".join(text_parts)

    m = VERSION_RE.search(full_text)
    if m:
        result["cch_version"] = m.group(1).replace(",", ".")

    storey_seen: list[str] = []
    for line in full_text.splitlines():
        s = line.strip().upper()
        if not s:
            continue
        if STOREY_RE.fullmatch(s) and s not in storey_seen:
            storey_seen.append(s)
    result["storey_names"] = [StoreyName(name=n) for n in storey_seen]

    zone_seen: list[str] = []
    for line in full_text.splitlines():
        s = line.strip()
        if ZONE_TYPE_RE.fullmatch(s) and s not in zone_seen:
            zone_seen.append(s)
    result["zone_specs"] = [ZoneSpec(name=None, type_label=z, localisation="PP") for z in zone_seen]

    room_seen: list[tuple[str, str, str]] = []
    for line in full_text.splitlines():
        m = ROOM_LINE_RE.match(line.strip())
        if not m:
            continue
        key = (m.group("name"), m.group("loc"), m.group("type"))
        if key not in room_seen:
            room_seen.append(key)
    result["room_specs"] = [
        RoomSpec(
            name=n,
            type_label=t,
            localisation=loc,
            surface_type=None,
        )
        for (n, loc, t) in room_seen
    ]
    return result
