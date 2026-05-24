"""Reporting de l'agent DOE — synthèse des correspondances."""
from __future__ import annotations

from collections import Counter
from typing import Iterable

from .models import Match


def summarize_matches(matches: Iterable[Match]) -> dict:
    """Construit un résumé exploitable : taux de matching, ambiguïtés, raisons."""
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
