"""Orchestrateur d'audit BIM : enchaîne toutes les règles et agrège.

Le moteur ne fait pas d'analyse lui-même : il délègue à 6 modules de
règles indépendants (``audit/rules/``) puis trie et empaquette les
findings dans un ``AuditResult`` sérialisable.

Pour ajouter une nouvelle règle :

1. Créer ``audit_bim/audit/rules/ma_regle.py`` avec une fonction
   ``audit_ma_regle(snap, catalog, phase) -> list[Finding]``.
2. L'exporter dans ``audit/rules/__init__.py``.
3. L'ajouter à ``run_audit`` dans ce fichier (ordre logique : spatial →
   nommage → classifs → propriétés → unicité → listes).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from ..extraction.model_data import ModelSnapshot
from ..requirements.models import BIMPhase, RequirementsCatalog
from .findings import Finding, Severity
from .rules import (
    audit_classifications,
    audit_lists,
    audit_naming,
    audit_properties,
    audit_spatial,
    audit_uniqueness,
)


@dataclass
class AuditResult:
    """Résultat complet d'un audit.

    Conteneur immuable produit par ``run_audit`` qui transporte :

    - le **contexte** (phase auditée, catalogue d'exigences, snapshot modèle)
    - les **anomalies** détectées (``findings``)
    - les **statistiques** dérivées via ``count_by_*`` et ``summary``

    Attributes:
        phase: Phase BIM auditée (APS → GESTION).
        catalog: Référentiel des exigences (extrait des 3 documents MOA).
        snapshot: Photo du modèle IFC depuis BIMData.
        findings: Liste triée des anomalies (sévérité décroissante puis
            thème puis type d'erreur).
    """

    phase: BIMPhase
    catalog: RequirementsCatalog
    snapshot: ModelSnapshot
    findings: list[Finding] = field(default_factory=list)

    # ── Statistiques ────────────────────────────────────────────────────────

    def count_by_theme(self) -> dict[str, int]:
        """Compte les findings par thème.

        Returns:
            Dict ``{theme_value: count}`` (utile pour le camembert Word).
        """
        return dict(Counter(f.theme.value for f in self.findings))

    def count_by_severity(self) -> dict[str, int]:
        """Compte les findings par sévérité.

        Returns:
            Dict ``{severity_value: count}`` — clés CRITICAL/HIGH/MEDIUM/
            LOW/INFO.
        """
        return dict(Counter(f.severity.value for f in self.findings))

    def count_by_error_type(self) -> dict[str, int]:
        """Compte les findings par type fin d'erreur.

        Returns:
            Dict ``{error_type_value: count}`` (1 onglet xlsx par type).
        """
        return dict(Counter(f.error_type.value for f in self.findings))

    def count_by_ifc_type(self) -> dict[str, int]:
        """Compte les findings par classe IFC réelle.

        Les anomalies projet (sans ``ifc_type``) sont comptées sous ``"?"``.

        Returns:
            Dict ``{ifc_class: count}``.
        """
        return dict(Counter((f.ifc_type or "?") for f in self.findings))

    def filter(
        self,
        *,
        theme: str | None = None,
        severity: str | None = None,
        error_type: str | None = None,
        ifc_type: str | None = None,
    ) -> list[Finding]:
        """Filtre les findings sur 1+ critères combinés en ET.

        Args:
            theme: Valeur ``Theme.value`` exacte (ex: ``"Nommage Pièce"``).
            severity: Valeur ``Severity.value`` exacte (ex: ``"HIGH"``).
            error_type: Valeur ``ErrorType.value`` exacte
                (ex: ``"classification_missing"``).
            ifc_type: Classe IFC exacte (ex: ``"IfcWallStandardCase"``).

        Returns:
            Liste filtrée — ordre préservé du tri initial.
        """
        out = list(self.findings)
        if theme:
            out = [f for f in out if f.theme.value == theme]
        if severity:
            out = [f for f in out if f.severity.value == severity]
        if error_type:
            out = [f for f in out if f.error_type.value == error_type]
        if ifc_type:
            out = [f for f in out if (f.ifc_type or "") == ifc_type]
        return out

    def conformity_rate(self) -> float:
        """Taux de conformité pondéré.

        Formule indicative — pas une métrique scientifique :
        ``1 - (anomalies_pondérées / (n_éléments × 3))``, plafonné à
        ``[0, 1]``. Les poids reflètent la gravité métier :

        ===========  =======
        Sévérité     Poids
        ===========  =======
        CRITICAL     5
        HIGH         3
        MEDIUM       1
        LOW          0.3
        INFO         0
        ===========  =======

        Returns:
            Flottant entre 0.0 (non conforme) et 1.0 (conforme). Sur un
            modèle APD typique, on observe 0.0–0.3.
        """
        weights = {
            Severity.CRITICAL: 5,
            Severity.HIGH: 3,
            Severity.MEDIUM: 1,
            Severity.LOW: 0.3,
            Severity.INFO: 0.0,
        }
        n_elements = max(1, len(self.snapshot.element_by_uuid))
        weighted = sum(weights.get(f.severity, 1) for f in self.findings)
        return max(0.0, min(1.0, 1.0 - (weighted / (n_elements * 3))))

    def summary(self) -> dict:
        """Résumé compact pour exposition MCP / API REST.

        Returns:
            Dict sérialisable JSON avec : phase, nb findings, ventilation
            par sévérité / thème / type d'erreur, taux de conformité,
            résumé du snapshot modèle.
        """
        return {
            "phase": self.phase.value,
            "n_findings": len(self.findings),
            "by_severity": self.count_by_severity(),
            "by_theme": self.count_by_theme(),
            "by_error_type": self.count_by_error_type(),
            "conformity_rate": round(self.conformity_rate(), 3),
            "model": self.snapshot.summary(),
        }


def run_audit(
    snap: ModelSnapshot,
    catalog: RequirementsCatalog,
    phase: BIMPhase,
) -> AuditResult:
    """Exécute la suite complète des règles d'audit et trie les findings.

    L'ordre d'exécution est fixé pour produire un dump JSON déterministe :

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

    Les findings sont ensuite triés par :
    sévérité décroissante > thème > type d'erreur > classe IFC > nom.

    Args:
        snap: Photo du modèle IFC (``extract_snapshot(client)``).
        catalog: Catalogue d'exigences agrégé (``build_catalog(...)``).
        phase: Phase BIM à auditer — détermine quelles propriétés sont
            exigées et active/désactive certaines règles (uniqueness à
            partir de DCE par ex.).

    Returns:
        ``AuditResult`` complet, prêt pour reporting et export.
    """
    findings: list[Finding] = []
    findings.extend(audit_spatial(snap, catalog, phase))
    findings.extend(audit_naming(snap, catalog))
    findings.extend(audit_classifications(snap, catalog, phase))
    findings.extend(audit_properties(snap, catalog, phase))
    findings.extend(audit_uniqueness(snap, catalog, phase))
    findings.extend(audit_lists(snap, catalog, phase))

    # Tri stable : sévérité décroissante puis thème puis type
    sev_order = {s: i for i, s in enumerate(Severity.ordered())}
    findings.sort(
        key=lambda f: (
            sev_order.get(f.severity, 99),
            f.theme.value,
            f.error_type.value,
            f.ifc_type or "",
            f.name or "",
        )
    )

    return AuditResult(phase=phase, catalog=catalog, snapshot=snap, findings=findings)
