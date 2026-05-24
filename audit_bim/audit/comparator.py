"""Comparaison de deux audits BIM — suivi des progressions entre 2 livraisons.

Cas d'usage MOA : la MOE livre une v1 du modèle, l'auditeur lance un
premier audit, signale les anomalies. Le MOE livre une v2 corrigée.
L'audit comparatif permet de répondre objectivement :

- Combien d'anomalies ont été **résolues** ?
- Combien sont **nouvelles** (régressions ou périmètre étendu) ?
- Combien **persistent** ?

La comparaison se fait par **signature** d'anomalie : un finding est
considéré identique entre deux audits s'il a la même
``(element_uuid, theme, error_type)``. Cette signature est assez fine
pour distinguer deux anomalies différentes sur le même objet (ex:
``classification_missing`` vs ``property_missing``) mais ignore les
variations de ``expected`` / ``actual`` (qui peuvent changer entre
versions sans que ce soit une « nouvelle » anomalie).

Pour les findings projet (sans ``element_uuid``), la signature inclut
``ifc_type`` à la place.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable
from enum import Enum
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

from .findings import Finding, Severity, Theme


class ChangeType(str, Enum):
    """Sortie de la comparaison pour chaque finding."""

    RESOLVED = "resolved"  # présent dans old, absent dans new
    NEW = "new"  # absent dans old, présent dans new
    PERSISTENT = "persistent"  # présent dans les deux


class ChangeEntry(BaseModel):
    """Détail d'une comparaison pour un finding.

    Attributes:
        change: Type d'évolution (RESOLVED/NEW/PERSISTENT).
        signature: Clé de regroupement utilisée.
        finding: Le finding (de ``new`` pour PERSISTENT/NEW, de
            ``old`` pour RESOLVED) — pour conserver le contexte
            (sévérité, thème, élément).
    """

    change: ChangeType
    signature: str
    finding: Finding


def _signature(f: Finding) -> str:
    """Construit la clé de comparaison d'un finding.

    Pour les findings sur élément : ``<theme>|<error_type>|<uuid>``.
    Pour les findings projet (sans uuid) : ``<theme>|<error_type>|<ifc_type>``.
    """
    if f.element_uuid:
        return f"{f.theme.value}|{f.error_type.value}|{f.element_uuid}"
    return f"{f.theme.value}|{f.error_type.value}|{f.ifc_type or 'project'}"


def compare_audits(
    old: Iterable[Finding],
    new: Iterable[Finding],
) -> list[ChangeEntry]:
    """Compare deux jeux de findings et classifie chaque ligne.

    Args:
        old: Findings du jeu *de référence* (typiquement audit
            précédent / livraison MOE v1).
        new: Findings du jeu *actuel* (audit du jour / livraison v2).

    Returns:
        Liste d'entrées ``ChangeEntry`` couvrant l'union des deux
        jeux. Ordre : RESOLVED d'abord, puis NEW, puis PERSISTENT
        (tri stable par signature à l'intérieur de chaque groupe).
    """
    old_by_sig: dict[str, Finding] = {_signature(f): f for f in old}
    new_by_sig: dict[str, Finding] = {_signature(f): f for f in new}

    old_sigs = set(old_by_sig)
    new_sigs = set(new_by_sig)

    entries: list[ChangeEntry] = []
    for sig in sorted(old_sigs - new_sigs):
        entries.append(
            ChangeEntry(change=ChangeType.RESOLVED, signature=sig, finding=old_by_sig[sig])
        )
    for sig in sorted(new_sigs - old_sigs):
        entries.append(ChangeEntry(change=ChangeType.NEW, signature=sig, finding=new_by_sig[sig]))
    for sig in sorted(old_sigs & new_sigs):
        entries.append(
            ChangeEntry(change=ChangeType.PERSISTENT, signature=sig, finding=new_by_sig[sig])
        )
    return entries


def summarize_changes(entries: list[ChangeEntry]) -> dict:
    """Compteurs d'évolution par sévérité, thème, type de changement.

    Args:
        entries: Sortie de :func:`compare_audits`.

    Returns:
        Dict avec :

        - ``n_total``
        - ``by_change`` : ``{resolved, new, persistent}``
        - ``by_change_x_severity`` : ``{resolved: {HIGH: ..., MEDIUM: ...}}``
        - ``by_change_x_theme`` : ``{resolved: {Theme: count}}``
        - ``progress_score`` : indicateur entre -1 (régression) et +1
          (correction). Formule : ``(resolved - new) / max(1, n_total)``.
    """
    by_change = Counter(e.change.value for e in entries)
    by_change_x_severity: dict[str, dict[str, int]] = {}
    by_change_x_theme: dict[str, dict[str, int]] = {}
    for e in entries:
        sev_map = by_change_x_severity.setdefault(e.change.value, Counter())
        sev_map[e.finding.severity.value] += 1
        theme_map = by_change_x_theme.setdefault(e.change.value, Counter())
        theme_map[e.finding.theme.value] += 1

    n_total = len(entries)
    progress = (by_change.get("resolved", 0) - by_change.get("new", 0)) / max(1, n_total)

    return {
        "n_total": n_total,
        "by_change": {
            "resolved": by_change.get("resolved", 0),
            "new": by_change.get("new", 0),
            "persistent": by_change.get("persistent", 0),
        },
        "by_change_x_severity": {k: dict(v) for k, v in by_change_x_severity.items()},
        "by_change_x_theme": {k: dict(v) for k, v in by_change_x_theme.items()},
        "progress_score": round(progress, 3),
    }


# ── Persistance / chargement JSON ────────────────────────────────────────


def load_findings_from_json(path: str | Path) -> list[Finding]:
    """Charge une liste de Finding depuis un fichier JSON.

    Format attendu : array d'objets sérialisés par ``Finding.model_dump(
    mode="json")`` (cf. fichier ``audit_*_findings.json`` produit par
    le CLI).

    Args:
        path: Chemin du fichier JSON.

    Returns:
        Liste de Finding désérialisés.

    Raises:
        FileNotFoundError: Si le fichier n'existe pas.
        ValueError: Si le contenu n'est pas une liste d'objets Finding.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(p)
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"Format invalide : attendu une liste, reçu {type(data).__name__}.")
    return [Finding.model_validate(item) for item in data]


def compare_audits_from_files(old_path: str | Path, new_path: str | Path) -> dict:
    """Compare deux fichiers d'audit JSON et renvoie un résumé MCP-friendly.

    Args:
        old_path: Fichier ``audit_*_findings.json`` de la version
            précédente.
        new_path: Fichier ``audit_*_findings.json`` de la version
            actuelle.

    Returns:
        Dict ``{summary, entries}`` avec :

        - ``summary`` : sortie de :func:`summarize_changes`
        - ``entries`` : 50 premières entrées (sérialisées JSON) pour
          préserver le canal MCP — l'exhaustif est dans le XLSX
          comparatif (généré séparément si besoin).
    """
    old_findings = load_findings_from_json(old_path)
    new_findings = load_findings_from_json(new_path)
    entries = compare_audits(old_findings, new_findings)
    summary = summarize_changes(entries)
    return {
        "old_source": str(old_path),
        "new_source": str(new_path),
        "summary": summary,
        "entries_sample": [
            {
                "change": e.change.value,
                "signature": e.signature,
                "severity": e.finding.severity.value,
                "theme": e.finding.theme.value,
                "error_type": e.finding.error_type.value,
                "ifc_type": e.finding.ifc_type,
                "name": e.finding.name,
                "element_uuid": e.finding.element_uuid,
            }
            for e in entries[:50]
        ],
        "n_old_findings": len(old_findings),
        "n_new_findings": len(new_findings),
    }


# ── Pour les non-utilisateurs des enums (verbose API) ────────────────────


def changes_by_type(entries: list[ChangeEntry]) -> dict[str, list[Finding]]:
    """Regroupe les ChangeEntry par type, pratique pour les reporters.

    Returns:
        Dict ``{change_type_value: [Finding, ...]}``.
    """
    out: dict[str, list[Finding]] = {ct.value: [] for ct in ChangeType}
    for e in entries:
        out[e.change.value].append(e.finding)
    return out


__all__ = [
    "ChangeEntry",
    "ChangeType",
    "changes_by_type",
    "compare_audits",
    "compare_audits_from_files",
    "load_findings_from_json",
    "summarize_changes",
]


# Garde-fou pour les imports type-checking
_ = Optional, Severity, Theme  # noqa: F841
