"""Agrégateur des 3 parseurs MOA → ``RequirementsCatalog`` unifié.

Politique de fusion :
- Le **xlsx** est la source autoritaire des exigences (priorité).
- Le **PDF** sert de complément (version du CCH, listes manquantes si une
  annexe n'a pas été fournie par le MOA).
"""

from __future__ import annotations

from pathlib import Path

from .data_spec_parser import parse_data_spec
from .models import RequirementsCatalog
from .naming_spec_parser import parse_naming_spec
from .pdf_parser import parse_pdf

# Cache module-level de ``build_catalog`` (PR4 §4c). Keyé sur les **chemins
# résolus + (mtime_ns, taille)** des 3 sources : un fichier modifié → clé
# différente → re-parse automatique. Pas de TTL, pas d'env de désactivation :
# le keying suffit. Un fichier fourni mais **absent** → pas de cache (le
# comportement d'erreur/partiel reste inchangé). Le flux courant « preview puis
# audit » économise ainsi un second parse complet (PDF + 2 xlsx).
_CATALOG_CACHE: dict[tuple, RequirementsCatalog] = {}


def clear_catalog_cache() -> None:
    """Vide le cache de ``build_catalog`` (fixture de tests / outil de debug)."""
    _CATALOG_CACHE.clear()


def _source_key(path: str | Path | None) -> tuple[str, int, int] | None:
    """``(chemin résolu, mtime_ns, taille)`` d'une source, ou ``None`` si absente."""
    if not path:
        return None
    p = Path(path)
    if not p.exists():
        return None
    st = p.stat()
    return (str(p.resolve()), st.st_mtime_ns, st.st_size)


def build_catalog(
    cch_pdf: str | Path | None = None,
    data_spec_xlsx: str | Path | None = None,
    naming_spec_xlsx: str | Path | None = None,
) -> RequirementsCatalog:
    """Construit (ou **réutilise depuis le cache**) un catalogue à partir des
    documents disponibles.

    Mémoïsé sur ``(chemin résolu, mtime, taille)`` des 3 sources — deux appels aux
    **mêmes** sources non modifiées renvoient le **même objet** (identité) ; toute
    modification d'un fichier force une reconstruction. Un fichier fourni mais
    absent désactive le cache (comportement inchangé).
    """
    provided = [x for x in (cch_pdf, data_spec_xlsx, naming_spec_xlsx) if x]
    if provided and all(Path(x).exists() for x in provided):
        key = (_source_key(cch_pdf), _source_key(data_spec_xlsx), _source_key(naming_spec_xlsx))
        cached = _CATALOG_CACHE.get(key)
        if cached is not None:
            return cached
        catalog = _build_catalog_uncached(cch_pdf, data_spec_xlsx, naming_spec_xlsx)
        _CATALOG_CACHE[key] = catalog
        return catalog
    # Aucune source, ou une source fournie manquante → pas de cache.
    return _build_catalog_uncached(cch_pdf, data_spec_xlsx, naming_spec_xlsx)


def _build_catalog_uncached(
    cch_pdf: str | Path | None = None,
    data_spec_xlsx: str | Path | None = None,
    naming_spec_xlsx: str | Path | None = None,
) -> RequirementsCatalog:
    """Construction effective (sans cache) — cf. :func:`build_catalog`."""
    catalog = RequirementsCatalog()

    if data_spec_xlsx and Path(data_spec_xlsx).exists():
        catalog.properties = parse_data_spec(data_spec_xlsx)
        catalog.data_spec_source = str(data_spec_xlsx)

    if naming_spec_xlsx and Path(naming_spec_xlsx).exists():
        rules, storeys, zones, rooms = parse_naming_spec(naming_spec_xlsx)
        catalog.naming_rules = rules
        catalog.storey_names = storeys
        catalog.zone_specs = zones
        catalog.room_specs = rooms
        catalog.naming_spec_source = str(naming_spec_xlsx)

    if cch_pdf and Path(cch_pdf).exists():
        pdf = parse_pdf(cch_pdf)
        catalog.cch_version = pdf.get("cch_version") or catalog.cch_version
        catalog.cch_source_pdf = str(cch_pdf)
        # Fallback : complète les listes vides
        if not catalog.storey_names:
            catalog.storey_names = pdf.get("storey_names") or []
        if not catalog.zone_specs:
            catalog.zone_specs = pdf.get("zone_specs") or []
        if not catalog.room_specs:
            catalog.room_specs = pdf.get("room_specs") or []

    return catalog
