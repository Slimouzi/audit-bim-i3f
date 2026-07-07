"""Rejoue ``run_audit`` sur des artefacts figés et dump findings/summary/agrégats.

Agnostique de la version : ``audit_bim`` est résolu depuis le CWD (worktree
courant), donc ``run_audit`` = celui de la version checkoutée. Lancer une fois
depuis le master (façade) et une fois depuis un worktree de l'ancien commit, puis
comparer les deux dumps avec ``compare.py``. **Read-only.**

⚠️ Le dump produit contient les ``Finding.model_dump()`` = **données client** : il
ne doit JAMAIS être versionné. Ce script **refuse** d'écrire dans le dépôt — passe
un chemin de sortie **hors du repo**.

Usage: python replay.py <artifacts_dir_hors_repo> <out.json_hors_repo> [phase]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def _assert_outside_repo(path: Path) -> None:
    root = Path(__file__).resolve()
    while root != root.parent and not (root / ".git").exists():
        root = root.parent
    p = path.resolve()
    if p == root or root in p.parents:
        raise SystemExit(
            f"REFUS : {p} est dans le dépôt {root}. Le dump contient des données "
            f"client — écris-le HORS du repo (ex. /tmp/engine-parity)."
        )


def main(argv: list[str]) -> int:
    if len(argv) not in (3, 4):
        print(
            "usage: python replay.py <artifacts_dir> <out.json> [phase]",
            file=sys.stderr,
        )
        return 2

    from bim_core.model_snapshot import ModelSnapshot

    from audit_bim.audit.engine import AuditResult, run_audit
    from audit_bim.mcp.security import set_runtime_transport

    set_runtime_transport("script")  # PR3 §3a — entrypoint local (writes/token permis)
    from audit_bim.requirements.models import BIMPhase, RequirementsCatalog

    art = Path(argv[1])
    outpath = Path(argv[2])
    _assert_outside_repo(outpath)
    phase = BIMPhase(argv[3]) if len(argv) == 4 else BIMPhase.AVP

    catalog = RequirementsCatalog.model_validate_json((art / "catalog.json").read_text())
    snap = ModelSnapshot(**json.loads((art / "snapshot.json").read_text()))

    result = run_audit(snap, catalog, phase)

    payload = {
        "auditresult_module": AuditResult.__module__,
        "run_audit_module": run_audit.__module__,
        "phase": phase.value,
        "n_findings": len(result.findings),
        # Ordre PRÉSERVÉ (liste, pas de tri) : la parité inclut l'ordre.
        "findings": [f.model_dump(mode="json") for f in result.findings],
        "summary": result.summary(),
        "by_severity": result.count_by_severity(),
        "by_theme": result.count_by_theme(),
        "by_error_type": result.count_by_error_type(),
        "by_ifc_type": result.count_by_ifc_type(),
        "conformity_rate": result.conformity_rate(),
    }
    outpath.write_text(json.dumps(payload, ensure_ascii=False))
    print(
        f"AuditResult module={AuditResult.__module__} "
        f"phase={phase.value} findings={len(result.findings)} -> {outpath}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
