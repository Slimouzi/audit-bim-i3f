"""Reporting de l'agent DOE — synthèse des correspondances."""
from __future__ import annotations

from collections import Counter
from collections.abc import Iterable

from .models import Match


def summarize_matches(matches: Iterable[Match]) -> dict:
    """Synthèse statistique d'une série de Match.

    Sert au reporting MCP / CLI et à la décision « apply / re-tune les
    seuils / abandonner » de l'auditeur.

    Args:
        matches: Itérable de Match issus de ``match_doe_records``.

    Returns:
        Dict avec :

        - ``n_records_total`` / ``n_matched`` / ``n_ambiguous`` /
          ``n_unmatched``
        - ``match_rate`` (0..1)
        - ``by_strategy`` : nb matches par stratégie (guid / tag / name)
        - ``by_confidence_band`` : nb matches par tranche de confiance
        - ``top_unmatch_reasons`` : top 5 raisons de non-match
    """
    items = list(matches)
    n_total = len(items)
    n_matched = sum(1 for m in items if m.is_matched())
    n_ambiguous = sum(1 for m in items if not m.is_matched() and m.candidates)
    n_unmatched = sum(1 for m in items if not m.is_matched() and not m.candidates)

    by_strategy = Counter(m.strategy for m in items if m.is_matched())
    confidence_bands = {"≥0.9": 0, "0.75–0.9": 0, "0.6–0.75": 0, "<0.6": 0}
    for m in items:
        if not m.is_matched():
            continue
        c = m.confidence
        if c >= 0.9:
            confidence_bands["≥0.9"] += 1
        elif c >= 0.75:
            confidence_bands["0.75–0.9"] += 1
        elif c >= 0.6:
            confidence_bands["0.6–0.75"] += 1
        else:
            confidence_bands["<0.6"] += 1

    reasons = Counter(m.reason for m in items if not m.is_matched() and m.reason)

    return {
        "n_records_total": n_total,
        "n_matched": n_matched,
        "n_ambiguous": n_ambiguous,
        "n_unmatched": n_unmatched,
        "match_rate": round(n_matched / n_total, 3) if n_total else 0,
        "by_strategy": dict(by_strategy),
        "by_confidence_band": confidence_bands,
        "top_unmatch_reasons": dict(reasons.most_common(5)),
    }
