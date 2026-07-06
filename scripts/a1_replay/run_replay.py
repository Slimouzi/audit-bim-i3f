"""Replay A1 industrialisé — publication BCF / Smart Views (prepare → review → apply).

Rejoue le protocole A1 prouvé (`docs/validation-a1-bim-publication-v0.1.0.md`) avec
un verdict machine, symétrique de l'acceptation AVP. **Dry-run par défaut** (aucune
écriture) ; `--write` déclenche l'écriture réelle **uniquement** sur le modèle de
validation jetable désigné par ``REPLAY_WRITE_MODEL_ID``.

⚠️ Le pack de plans (scellés) reste **hors du dépôt** ; la sortie stdout ne porte
que compteurs / booléens / verdict (aucune donnée client). Politique identique à
`scripts/avp_acceptance/`.

Usage:
    python run_replay.py <out_dir_hors_repo> [--write] [phase]

Cf. `docs/scope-a1-replay.md` (décisions figées A/B/C).
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

# ── Attendus DÉTERMINISTES (décision C figée) — cible + filtre + compte ────
# Modèle jetable de validation (Dieppe) et filtre figés : le compte attendu est
# déterministe. Une évolution légitime de la maquette = un diff d'une ligne, revu.
EXPECTED_BCF_TOPICS = 1
EXPECTED_SMART_VIEWS = 1
DISPOSABLE_MODEL_NAME_FRAGMENT = "DIEPPE"  # contrôle d'identité (verify_active_model)
REPLAY_ERROR_TYPES = ["naming_invalid_format"]
REPLAY_INCLUDE_OVERVIEW = False
PREFIX_BASE = "REPLAY-BIM-PUBLICATION-"  # + YYYYMMDD + " — "


def expected_prefix(date_yyyymmdd: str) -> str:
    """Préfixe daté des objets créés (convention de purge, décision A)."""
    return f"{PREFIX_BASE}{date_yyyymmdd} — "


def _assert_outside_repo(out: Path) -> None:
    root = Path(__file__).resolve()
    while root != root.parent and not (root / ".git").exists():
        root = root.parent
    out = out.resolve()
    if out == root or root in out.parents:
        raise SystemExit(
            f"REFUS : {out} est dans le dépôt {root}. Les plans/sorties peuvent porter "
            f"des données client — écris-les HORS du repo (ex. /tmp/a1-replay)."
        )


def assert_write_target(effective_target: dict, allowed_model_id: str | None) -> None:
    """Garde **cible jetable** (helper pur) : l'écriture n'est autorisée QUE sur le
    modèle de validation désigné par ``REPLAY_WRITE_MODEL_ID``. Toute autre cible →
    ``SystemExit`` **avant** tout ``apply`` (même esprit que ``_assert_outside_repo``)."""
    if not allowed_model_id:
        raise SystemExit(
            "REFUS : REPLAY_WRITE_MODEL_ID non défini — écriture réelle interdite "
            "(le modèle jetable autorisé doit être explicite)."
        )
    eff = str(effective_target.get("model_id") or "")
    if eff != str(allowed_model_id):
        raise SystemExit(
            f"REFUS : cible d'écriture model_id={eff!r} ≠ modèle jetable autorisé "
            f"{allowed_model_id!r}. Écriture refusée avant tout apply."
        )


def inspect_plan(plan, *, effective_target: dict, title_prefix: str, min_items: int = 1) -> dict:
    """Revue **pure** d'un ``WritePlan`` — compteurs/booléens, aucune donnée client.

    ``ok`` exige : ``n_items >= min_items``, **aucun risque**, ``target`` == cible
    effective (cloud/project/model), et **tous** les titres d'objets préfixés par
    ``title_prefix``. Seuils identiques côté runner et tests (un seul helper).
    """
    items = list(getattr(plan, "items", None) or [])
    risks = list(getattr(plan, "risks", None) or [])
    target = getattr(plan, "target", None) or {}

    n_items = len(items)
    has_risks = bool(risks)
    target_matches = all(
        str(target.get(k) or "") == str(effective_target.get(k) or "")
        for k in ("cloud_id", "project_id", "model_id")
    )
    titles = [str(it.get("title") or "") for it in items]
    prefix_ok = bool(titles) and all(t.startswith(title_prefix) for t in titles)

    ok = n_items >= min_items and not has_risks and target_matches and prefix_ok
    return {
        "n_items": n_items,
        "has_risks": has_risks,
        "target_matches": target_matches,
        "prefix_ok": prefix_ok,
        "ok": ok,
    }


def _plan_report(review: dict, expected_count: int) -> dict:
    count_ok = review["n_items"] == expected_count
    return {
        **review,
        "expected_items": expected_count,
        "count_ok": count_ok,
        "ok": review["ok"] and count_ok,
    }


def main(argv: list[str]) -> int:  # noqa: C901 (séquence linéaire lisible)
    args = [a for a in argv[1:] if a != "--write"]
    write = "--write" in argv
    if not args:
        print("usage: python run_replay.py <out_dir_hors_repo> [--write] [phase]", file=sys.stderr)
        return 2

    import os

    from audit_bim import config
    from audit_bim.actions.bcf_planner import apply_bcf, prepare_bcf
    from audit_bim.actions.plans import load_plan, save_plan
    from audit_bim.actions.smartview_planner import apply_smart_views, prepare_smart_views
    from audit_bim.audit.engine import run_audit
    from audit_bim.domain.filters import FindingFilter
    from audit_bim.extraction.client import BIMDataClient
    from audit_bim.extraction.model_data import extract_snapshot
    from audit_bim.mcp.tools_actions import apply_bcf_topics  # confirm gate (early-return)
    from audit_bim.requirements.catalog import build_catalog
    from audit_bim.requirements.models import BIMPhase

    out = Path(args[0])
    _assert_outside_repo(out)
    out.mkdir(parents=True, exist_ok=True)
    os.environ["AUDIT_OUTPUT_DIR"] = str(out)  # plans scellés écrits hors repo
    phase = BIMPhase(args[1]) if len(args) > 1 else BIMPhase.AVP

    # 1. Cible explicite + contrôle d'identité (nom de modèle attendu).
    client = BIMDataClient()
    snap = extract_snapshot(client)
    model_name = (snap.model or {}).get("name") or ""
    identity_ok = DISPOSABLE_MODEL_NAME_FRAGMENT.casefold() in model_name.casefold()
    if not identity_ok:
        raise SystemExit(
            f"REFUS : identité cible non conforme — modèle actif ne contient pas "
            f"{DISPOSABLE_MODEL_NAME_FRAGMENT!r}."
        )
    effective_target = {
        "cloud_id": client.cloud_id,
        "project_id": client.project_id,
        "model_id": client.model_id,
    }

    # 3. Audit réel (catalogue CCH complet).
    catalog = build_catalog(
        cch_pdf=config.I3F_CCH_PDF,
        data_spec_xlsx=config.I3F_DATA_SPEC_XLSX,
        naming_spec_xlsx=config.I3F_NAMING_SPEC_XLSX,
    )
    _docs = {
        "cch_pdf": config.I3F_CCH_PDF,
        "data_spec_xlsx": config.I3F_DATA_SPEC_XLSX,
        "naming_spec_xlsx": config.I3F_NAMING_SPEC_XLSX,
    }
    _missing = [n for n, p in _docs.items() if not p or not Path(p).exists()]
    if _missing:
        raise SystemExit(f"REFUS : documents I3F absents {_missing} — contrôle CCH impossible.")
    if not catalog.properties or not catalog.naming_rules:
        raise SystemExit("REFUS : catalogue CCH vide — replay non fiable.")
    result = run_audit(snap, catalog, phase)

    # 4. Préparation — plans scellés (aucune écriture). Filtre + préfixe figés.
    date = datetime.now().strftime("%Y%m%d")
    prefix = expected_prefix(date)
    ffilter = FindingFilter(error_types=REPLAY_ERROR_TYPES)
    bcf_plan = prepare_bcf(
        result,
        finding_filter=ffilter,
        target=effective_target,
        prefix=prefix,
        include_overview=REPLAY_INCLUDE_OVERVIEW,
    )
    sv_plan = prepare_smart_views(
        result,
        finding_filter=ffilter,
        target=effective_target,
        prefix=prefix,
        include_overview=REPLAY_INCLUDE_OVERVIEW,
    )

    # 5. Revue automatique (helper pur) + compte déterministe.
    bcf_review = _plan_report(
        inspect_plan(bcf_plan, effective_target=effective_target, title_prefix=prefix),
        EXPECTED_BCF_TOPICS,
    )
    sv_review = _plan_report(
        inspect_plan(sv_plan, effective_target=effective_target, title_prefix=prefix),
        EXPECTED_SMART_VIEWS,
    )

    report: dict = {
        "mode": "write" if write else "dry-run",
        "phase": phase.value,
        "bcf_plan": bcf_review,
        "smart_views_plan": sv_review,
    }
    review_ok = bcf_review["ok"] and sv_review["ok"]

    if not write:
        # Dry-run : PASS possible sans écrire (mode planifiable, décision B).
        report["verdict"] = "PASS" if review_ok else "FAIL"
        print(json.dumps(report, ensure_ascii=False, indent=2))
        print("VERDICT:", report["verdict"])
        return 0 if review_ok else 1

    # ── Mode --write (manuel uniquement, décision B) ──────────────────────
    if not review_ok:
        report["verdict"] = "FAIL"
        print(json.dumps(report, ensure_ascii=False, indent=2))
        print("VERDICT: FAIL (revue de plan non conforme — aucune écriture)")
        return 1

    # 2. Garde cible jetable — refus avant tout apply si cible ≠ modèle autorisé.
    assert_write_target(effective_target, os.getenv("REPLAY_WRITE_MODEL_ID"))

    bcf_path = save_plan(bcf_plan)
    sv_path = save_plan(sv_plan)

    # 6. Garde-fou négatif rejoué : apply(confirm=False) → refus prouvé.
    neg_bcf = apply_bcf_topics(str(bcf_path), confirm=False)
    report["guardrail_confirm_false_refused"] = bool(neg_bcf.get("refused"))
    if not neg_bcf.get("refused"):
        raise SystemExit("REFUS : le garde-fou confirm=False n'a pas refusé — arrêt.")

    # 7. Apply confirm=True (chemin Python planner).
    bcf_res = apply_bcf(load_plan(bcf_path), client, actual_target=effective_target)
    sv_res = apply_smart_views(load_plan(sv_path), client, actual_target=effective_target)
    report["bcf_apply"] = {"succeeded": bcf_res.succeeded, "failed": bcf_res.failed}
    report["smart_views_apply"] = {"succeeded": sv_res.succeeded, "failed": sv_res.failed}

    # 8. Vérification post-apply : le compte appliqué doit matcher l'attendu.
    #    NOTE : la relecture INDÉPENDANTE via l'API (list topics/views) nécessite
    #    un endpoint de liste absent de bimdata-read — prérequis borné à ajouter
    #    (cf. scope §4 / suivi). En attendant, on vérifie succeeded == attendu +
    #    failed == 0 (rapport d'apply + journal).
    write_ok = (
        bcf_res.succeeded == EXPECTED_BCF_TOPICS
        and bcf_res.failed == 0
        and sv_res.succeeded == EXPECTED_SMART_VIEWS
        and sv_res.failed == 0
    )
    report["verdict"] = "PASS" if write_ok else "FAIL"
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print("VERDICT:", report["verdict"])
    return 0 if write_ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
