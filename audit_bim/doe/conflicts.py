"""Détection des conflits DOE ↔ valeurs existantes dans la maquette.

Sécurité : avant d'écrire un Pset DOE sur un élément IFC, on vérifie si
une valeur est déjà présente pour la même propriété. 4 cas possibles :

- ``MATCH``    : valeur existante == valeur DOE → rien à faire (skip).
- ``NEW``      : aucune valeur existante → écriture normale.
- ``UPGRADE``  : valeur existante vide/whitespace → écriture (équiv. NEW).
- ``CONFLICT`` : valeur existante différente → arbitrage requis.

Stratégie ``on_conflict`` côté enricher :

- ``"report"`` (défaut) : écrit les NEW/UPGRADE. Les CONFLICT sont
  *signalés* dans le rapport mais **non écrits** (pas d'écrasement
  silencieux). Mode recommandé pour un audit prudent.
- ``"skip"`` : comme ``report`` mais sans détail nominal des conflits.
- ``"overwrite"`` : écrase aussi les CONFLICT. À utiliser uniquement
  quand le DOE est *autoritaire* (post-réception, validé MOA).

L'inspection des valeurs existantes se fait sur le ``ModelSnapshot``
local (pas d'API call supplémentaire). Limitation V1 : si l'utilisateur
lance ``doe_enrich_model`` deux fois sans ``extract_model_snapshot``
entre les deux, le 2e run croira que les valeurs n'existent pas. À
re-snapshoter après enrichissement.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from ..extraction.model_data import ModelSnapshot
from ..extraction.normalizer import resolve_value
from .models import Match


class ConflictType(str, Enum):
    """Classification d'une comparaison (existant, DOE)."""

    MATCH = "match"
    NEW = "new"
    UPGRADE = "upgrade"
    CONFLICT = "conflict"


class ConflictReport(BaseModel):
    """Détail d'une comparaison existant ↔ DOE pour une propriété donnée."""

    type: ConflictType
    element_uuid: str
    ifc_type: str | None = None
    ifc_name: str | None = None
    pset: str
    property: str = Field(..., alias="property_name")
    existing_value: Any | None = None
    doe_value: Any | None = None

    model_config = {"populate_by_name": True}


def _values_equal(a: Any, b: Any) -> bool:
    """Compare deux valeurs avec tolérance type.

    Règles :
    - Strings comparées après strip + casefold.
    - Nombres int/float comparés numériquement (4.0 == 4 == "4").
    - Booléens : True == True ; True == "V" / "Oui" / "1" ; etc.
    - None vs vide → géré par l'appelant (ConflictType.NEW/UPGRADE).
    """
    if a is None or b is None:
        return a is b
    # Booléens : compare via la même normalisation que validators
    if isinstance(a, bool) or isinstance(b, bool):
        return _to_bool(a) == _to_bool(b)
    # Numériques
    try:
        return float(a) == float(b)
    except (TypeError, ValueError):
        pass
    # Chaînes (insensible casse + accents normalisés simplement)
    sa = str(a).strip().casefold()
    sb = str(b).strip().casefold()
    return sa == sb


def _to_bool(v: Any) -> bool | None:
    """Convertit une valeur libre en booléen Python ou ``None`` si ambigu."""
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v) if v in (0, 1) else None
    if isinstance(v, str):
        s = v.strip().upper()
        if s in ("V", "TRUE", "OUI", "1", "VRAI", "YES"):
            return True
        if s in ("F", "FALSE", "NON", "0", "FAUX", "NO"):
            return False
    return None


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    return False


def classify_conflict(existing: Any, doe_value: Any) -> ConflictType:
    """Compare existant vs DOE et renvoie le type de relation.

    Args:
        existing: Valeur actuellement dans la maquette (peut être ``None``).
        doe_value: Valeur proposée par le DOE.

    Returns:
        Un ``ConflictType`` :

        - ``NEW`` si l'existant est ``None`` (pas de propriété).
        - ``UPGRADE`` si l'existant est une chaîne vide / whitespace.
        - ``MATCH`` si les valeurs sont égales selon ``_values_equal``.
        - ``CONFLICT`` sinon.
    """
    if existing is None:
        return ConflictType.NEW
    if isinstance(existing, str) and not existing.strip():
        return ConflictType.UPGRADE
    if _values_equal(existing, doe_value):
        return ConflictType.MATCH
    return ConflictType.CONFLICT


def detect_conflicts(
    matches: list[Match],
    snapshot: ModelSnapshot,
) -> list[ConflictReport]:
    """Construit le rapport de conflits pour une série de Match.

    Pour chaque (match, pset, propriété DOE), récupère la valeur
    existante dans le snapshot et la classifie.

    Args:
        matches: Liste de Match (les non-matchés sont ignorés).
        snapshot: ModelSnapshot du modèle IFC (utilisé pour
            ``element_by_uuid`` et la lecture des Psets existants).

    Returns:
        Liste de ConflictReport, un par propriété DOE × élément matché.
    """
    reports: list[ConflictReport] = []
    by_uuid = snapshot.element_by_uuid
    for m in matches:
        if not m.is_matched():
            continue
        el = by_uuid.get(m.ifc_uuid or "")
        if el is None:
            # Match pointant un UUID absent du snapshot (cas rare)
            continue
        for pset_name, props in (m.record.properties or {}).items():
            for prop_name, doe_value in props.items():
                existing = resolve_value(el, pset_name, prop_name)
                ctype = classify_conflict(existing, doe_value)
                reports.append(
                    ConflictReport(
                        type=ctype,
                        element_uuid=m.ifc_uuid,
                        ifc_type=m.ifc_type,
                        ifc_name=m.ifc_name,
                        pset=pset_name,
                        property_name=prop_name,
                        existing_value=existing,
                        doe_value=doe_value,
                    )
                )
    return reports


def summarize_conflicts(reports: list[ConflictReport]) -> dict:
    """Compteurs par type pour exposition MCP / reporting.

    Args:
        reports: Liste de ConflictReport.

    Returns:
        Dict ``{by_type: {match, new, upgrade, conflict}, n_total}``.
    """
    from collections import Counter

    by_type = Counter(r.type.value for r in reports)
    return {
        "n_total": len(reports),
        "by_type": {
            "match": by_type.get("match", 0),
            "new": by_type.get("new", 0),
            "upgrade": by_type.get("upgrade", 0),
            "conflict": by_type.get("conflict", 0),
        },
    }
