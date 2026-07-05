"""Comparateur de parité moteur — n'émet QUE des hashes, compteurs et verdict.

Ne lit jamais de secret et **n'imprime aucune donnée client** (ni nom, ni uuid,
ni valeur de finding) : uniquement des empreintes SHA-256, des compteurs, des
booléens et — en cas de divergence — l'**index** du premier écart (jamais son
contenu). La sortie est donc sûre à archiver comme preuve.

Usage: python compare.py <new.json> <old.json>  # exit 0 si parité, 1 sinon
"""

from __future__ import annotations

import hashlib
import json
import sys

# Sections agrégées comparées telles quelles (pas de contenu client : ce sont
# des compteurs / dictionnaires de compteurs / la valeur de phase).
_SCALAR_KEYS = (
    "phase",
    "n_findings",
    "summary",
    "by_severity",
    "by_theme",
    "by_error_type",
    "by_ifc_type",
    "conformity_rate",
)


def _h(obj: object) -> str:
    """SHA-256 d'une valeur JSON canonicalisée (clés triées)."""
    return hashlib.sha256(
        json.dumps(obj, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _first_divergence_index(a: list, b: list) -> int | None:
    """Index du premier élément différent (aucun contenu renvoyé)."""
    for i, (x, y) in enumerate(zip(a, b, strict=False)):
        if x != y:
            return i
    if len(a) != len(b):
        return min(len(a), len(b))
    return None


def compare(new: dict, old: dict) -> dict:
    """Compare deux dumps de replay et renvoie un verdict **sans donnée client**.

    Le dump attendu (produit par ``replay.py``) contient : ``auditresult_module``,
    les sections agrégées de :data:`_SCALAR_KEYS`, et ``findings`` (liste de
    ``Finding.model_dump()``). Seules des **empreintes** de ``findings`` sont
    exposées, jamais leur contenu.
    """
    nf = new.get("findings", [])
    of = old.get("findings", [])

    checks: dict[str, bool] = {key: new.get(key) == old.get(key) for key in _SCALAR_KEYS}
    checks["findings_len"] = len(nf) == len(of)
    checks["findings_hash"] = _h(nf) == _h(of)  # ordre + contenu

    ok = all(checks.values())
    return {
        "engine_new": new.get("auditresult_module"),
        "engine_old": old.get("auditresult_module"),
        "distinct_engines": new.get("auditresult_module") != old.get("auditresult_module"),
        "n_findings_new": len(nf),
        "n_findings_old": len(of),
        "findings_hash_new": _h(nf),
        "findings_hash_old": _h(of),
        "first_divergence_index": None
        if checks["findings_hash"]
        else _first_divergence_index(nf, of),
        "checks": checks,
        "ok": ok,
    }


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: python compare.py <new.json> <old.json>", file=sys.stderr)
        return 2
    with open(argv[1], encoding="utf-8") as fh:
        new = json.load(fh)
    with open(argv[2], encoding="utf-8") as fh:
        old = json.load(fh)
    verdict = compare(new, old)
    # Sortie sûre : uniquement hashes / compteurs / booléens.
    print(json.dumps(verdict, ensure_ascii=False, indent=2))
    print("VERDICT:", "PARITÉ EXACTE" if verdict["ok"] else "DIVERGENCE")
    return 0 if verdict["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
