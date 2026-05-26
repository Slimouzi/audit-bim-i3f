"""Modèles métier stables, indépendants des sources (BIMData, DOE, datagouv).

Cette couche est la **frontière** entre :

- les sources d'extraction (``extraction/``, ``doe/``, ``enrichment/``) qui
  produisent des dicts dénormalisés spécifiques à chaque API ;
- les couches d'analyse (``audit/``, ``classifier/``, ``query/``) et de
  sortie (``reporting/``, ``bcf/``, ``smartview/``, ``actions/``) qui ne
  doivent connaître que ces modèles stables.

Objectif : permettre l'ajout d'une nouvelle source (datagouv, IFC local,
ERP/GMAO) sans toucher aux règles d'audit ni aux exporteurs.

Modèles exposés
---------------

- :class:`BimObject` — adaptateur stable d'un élément modélisé,
  indépendant du payload BIMData ``/element/raw``.
- :class:`ObjectFilter` — filtre déclaratif sur :class:`BimObject`.
- :class:`FindingFilter` — filtre déclaratif sur ``Finding``.
- :class:`SuggestionFilter` — filtre déclaratif sur
  ``ClassificationSuggestionEntry``.
- :class:`WritePlan` / :class:`ActionResult` — squelettes pour le pattern
  *prepare → validate → apply* (utilisés à partir de la tranche 2).
"""

from __future__ import annotations

from .bim_object import BimObject, ClassificationRef
from .filters import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    ConfidenceBand,
    FindingFilter,
    ObjectFilter,
    SuggestionFilter,
    SuggestionStatus,
)
from .write_plan import ActionResult, WritePlan, WritePlanKind

__all__ = [
    "BimObject",
    "ClassificationRef",
    "ObjectFilter",
    "FindingFilter",
    "SuggestionFilter",
    "ConfidenceBand",
    "SuggestionStatus",
    "DEFAULT_LIMIT",
    "MAX_LIMIT",
    "WritePlan",
    "WritePlanKind",
    "ActionResult",
]
