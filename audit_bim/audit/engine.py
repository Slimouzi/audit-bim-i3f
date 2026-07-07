"""Façade I3F du moteur d'audit générique ``bim-audit-engine``.

Le cœur du moteur (protocole ``Rule``, boucle ``run_audit`` à règles injectables,
conteneur générique ``AuditResult`` + tri déterministe) vit désormais dans le
package first-party ``bim-audit-engine`` (dépend de ``bim-core`` uniquement). Ce
module est la **façade I3F** : il ne réimplémente rien, il câble le jeu de règles
I3F sur le moteur générique.

- ``AuditResult`` est **ré-exporté tel quel** depuis ``bim_audit_engine`` — c'est
  le **même objet** (``audit_bim.audit.engine.AuditResult is
  bim_audit_engine.AuditResult``). Aucun changement de champs/méthodes/dump.
- ``run_audit(snap, catalog, phase)`` conserve **exactement** la signature et le
  comportement historiques : elle injecte ``I3F_RULES`` (les 6 règles I3F, dans
  l'ordre historique) dans ``bim_audit_engine.run_audit``. Parité prouvée par
  **équivalence** (mêmes findings, même tri), pas par identité de la fonction
  (la façade lie les règles, le moteur ne les connaît pas).

Restent **côté I3F**, inchangés : le catalogue (``RequirementsCatalog``), la
phase (``BIMPhase``), les 6 règles concrètes (``audit/rules/``), les helpers
(``validators``, ``ifc_taxonomy``, ``normalizer``) et ``preliminary``.

Pour ajouter une règle : créer ``audit_bim/audit/rules/ma_regle.py`` avec
``audit_ma_regle(snap, catalog, phase) -> list[Finding]``, l'exporter dans
``audit/rules/__init__.py`` puis l'ajouter à ``I3F_RULES`` ci-dessous (l'ordre
fixe le dump).
"""

from __future__ import annotations

from bim_audit_engine import AuditResult
from bim_audit_engine import run_audit as _engine_run_audit

from ..extraction.model_data import ModelSnapshot
from ..requirements.models import BIMPhase, RequirementsCatalog
from .rules import (
    audit_classifications,
    audit_lists,
    audit_naming,
    audit_properties,
    audit_spatial,
    audit_uniqueness,
)

# Jeu de règles I3F, dans l'ordre historique qui fixe le dump JSON :
# spatial → nommage → classifications → propriétés → unicité → listes.
# ``audit_naming`` accepte désormais ``phase`` (ignoré) pour respecter le
# protocole ``Rule`` ``(snap, catalog, phase) -> list[Finding]``.
I3F_RULES = (
    audit_spatial,
    audit_naming,
    audit_classifications,
    audit_properties,
    audit_uniqueness,
    audit_lists,
)


def run_audit(
    snap: ModelSnapshot,
    catalog: RequirementsCatalog,
    phase: BIMPhase,
) -> AuditResult:
    """Exécute la suite complète des règles d'audit I3F et trie les findings.

    Façade : délègue au moteur générique en injectant ``I3F_RULES``. Le résultat
    est **identique** à l'ancienne implémentation en dur (mêmes règles, même
    ordre, même tri déterministe sévérité↓ > thème > type d'erreur > classe IFC >
    nom).

    1. ``audit_spatial`` — hiérarchie Site/Bât/Étage/Espace, quantités
       (SHAB/SU), géoréférencement.
    2. ``audit_naming`` — conventions CCH chap. 6.3 (codification I3F,
       listes fermées étages/zones/pièces).
    3. ``audit_classifications`` — présence + complétude + cohérence
       niveau 3 (familles acceptées par classe IFC).
    4. ``audit_properties`` — Psets/propriétés requis à la phase BIM cible
       (avec expansion sous-classes IFC) + validation des valeurs.
    5. ``audit_uniqueness`` (à partir de DCE) — identifiant équipement
       (Tag/Mark) présent et unique.
    6. ``audit_lists`` — couverture des typologies du référentiel
       (zones PC absentes, etc.).

    Args:
        snap: Photo du modèle IFC (``extract_snapshot(client)``).
        catalog: Catalogue d'exigences agrégé (``build_catalog(...)``).
        phase: Phase BIM à auditer — détermine quelles propriétés sont
            exigées et active/désactive certaines règles (uniqueness à
            partir de DCE par ex.).

    Returns:
        ``AuditResult`` complet, prêt pour reporting et export.
    """
    return _engine_run_audit(snap, catalog, phase, rules=I3F_RULES)


__all__ = ["AuditResult", "run_audit", "I3F_RULES"]
