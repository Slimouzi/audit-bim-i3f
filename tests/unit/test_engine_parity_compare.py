"""Test synthétique du comparateur de parité moteur (`scripts/engine_parity`).

Données 100 % factices (aucune donnée client) : on vérifie la logique du verdict
— parité exacte, divergence d'ordre, divergence d'agrégat, longueurs différentes,
et l'absence de fuite de contenu dans la sortie.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

# Charge compare.py par chemin (il vit sous scripts/, hors du package audit_bim).
_COMPARE_PATH = Path(__file__).resolve().parents[2] / "scripts" / "engine_parity" / "compare.py"
_spec = importlib.util.spec_from_file_location("engine_parity_compare", _COMPARE_PATH)
compare_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(compare_mod)


def _finding(name: str, sev: str = "HIGH") -> dict:
    return {"name": name, "severity": sev, "theme": "T", "error_type": "E", "ifc_type": "IfcWall"}


def _payload(findings: list[dict], *, module: str, by_severity: dict | None = None) -> dict:
    return {
        "auditresult_module": module,
        "phase": "AVP",
        "n_findings": len(findings),
        "summary": {"phase": "AVP", "n_findings": len(findings)},
        "by_severity": by_severity or {"HIGH": len(findings)},
        "by_theme": {"T": len(findings)},
        "by_error_type": {"E": len(findings)},
        "by_ifc_type": {"IfcWall": len(findings)},
        "conformity_rate": 0.5,
        "findings": findings,
    }


def test_exact_parity_distinct_engines():
    f = [_finding("a"), _finding("b")]
    new = _payload(list(f), module="bim_audit_engine.result")
    old = _payload(list(f), module="audit_bim.audit.engine")
    v = compare_mod.compare(new, old)
    assert v["ok"] is True
    assert v["first_divergence_index"] is None
    assert all(v["checks"].values())
    # Discriminant de version : moteurs distincts mais résultats identiques.
    assert v["distinct_engines"] is True
    assert v["findings_hash_new"] == v["findings_hash_old"]


def test_order_divergence_detected():
    new = _payload([_finding("a"), _finding("b")], module="m1")
    old = _payload([_finding("b"), _finding("a")], module="m2")
    v = compare_mod.compare(new, old)
    assert v["ok"] is False
    assert v["checks"]["findings_hash"] is False
    assert v["first_divergence_index"] == 0
    assert v["findings_hash_new"] != v["findings_hash_old"]


def test_aggregate_divergence_detected():
    f = [_finding("a")]
    new = _payload(list(f), module="m1", by_severity={"HIGH": 1})
    old = _payload(list(f), module="m2", by_severity={"LOW": 1})
    v = compare_mod.compare(new, old)
    assert v["ok"] is False
    assert v["checks"]["by_severity"] is False
    # Les findings eux-mêmes sont identiques → pas d'index de divergence findings.
    assert v["checks"]["findings_hash"] is True
    assert v["first_divergence_index"] is None


def test_length_divergence_detected():
    new = _payload([_finding("a"), _finding("b")], module="m1")
    old = _payload([_finding("a")], module="m2")
    v = compare_mod.compare(new, old)
    assert v["ok"] is False
    assert v["checks"]["findings_len"] is False
    assert v["first_divergence_index"] == 1


def test_output_leaks_no_client_content():
    # La sortie ne doit contenir que hashes / compteurs / booléens / index :
    # aucune valeur de finding (ex. le nom "secret-name") ne doit fuiter.
    new = _payload([_finding("secret-name")], module="m1")
    old = _payload([_finding("secret-name")], module="m2")
    v = compare_mod.compare(new, old)
    import json

    dumped = json.dumps(v, ensure_ascii=False)
    assert "secret-name" not in dumped
