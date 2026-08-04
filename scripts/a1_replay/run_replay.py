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
# Contrôle d'identité par **nom exact** attendu (pas un simple fragment) : côté
# écriture on n'accepte que la maquette jetable désignée.
EXPECTED_MODEL_NAME = "DIEPPE-7427L-BATA-ARCHI-APD.ifc"
REPLAY_ERROR_TYPES = ["naming_invalid_format"]
REPLAY_INCLUDE_OVERVIEW = False
PREFIX_BASE = "REPLAY-BIM-PUBLICATION-"  # + YYYYMMDD + " — "


def expected_prefix(date_yyyymmdd: str) -> str:
    """Préfixe daté des objets créés (convention de purge, décision A)."""
    return f"{PREFIX_BASE}{date_yyyymmdd} — "


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


def journal_confirms(entries, *, action: str, plan_id: str, expected_succeeded: int) -> bool:
    """Vrai si le journal (``audit_trail``) contient une entrée **de ce run** —
    ``action`` + ``plan_id`` — avec ``succeeded == attendu`` et ``failed == 0``.

    Vérification **indépendante** du retour d'``apply`` (étape 9 du scope). Pure,
    testable hors réseau (entrées = objets à attributs ``action/plan_id/succeeded/
    failed``)."""
    return any(
        getattr(e, "action", None) == action
        and getattr(e, "plan_id", None) == plan_id
        and getattr(e, "succeeded", None) == expected_succeeded
        and getattr(e, "failed", None) == 0
        for e in entries
    )


def verify_published(topics, *, title_prefix: str, expected_count: int) -> dict:
    """Re-lecture **indépendante** (étape 8) : parmi les topics/views RELUS via
    l'API, compter ceux au **préfixe daté de ce run** (``title_prefix``) et
    vérifier ``== expected_count``. Pur, testable hors réseau (topics = liste de
    dicts à clé ``title``). Sortie = compteurs/booléens (aucune donnée client)."""
    n = sum(1 for t in topics if str((t or {}).get("title") or "").startswith(title_prefix))
    return {"n_published": n, "count_ok": n == expected_count}


def select_purge_guids(topics, *, title_prefix: str) -> list[str]:
    """Sélection **pure** des ``guid`` à purger : parmi les topics/views RELUS,
    ceux au **préfixe daté de ce run** (``title_prefix``). Testable hors réseau
    (topics = liste de dicts à clés ``title``/``guid``). Clé BCF 2.1 = ``guid``
    (repli ``id`` par prudence)."""
    guids: list[str] = []
    for t in topics or []:
        t = t or {}
        if str(t.get("title") or "").startswith(title_prefix):
            g = t.get("guid") or t.get("id")
            if g:
                guids.append(str(g))
    return guids


def _plan_report(review: dict, expected_count: int) -> dict:
    count_ok = review["n_items"] == expected_count
    return {
        **review,
        "expected_items": expected_count,
        "count_ok": count_ok,
        "ok": review["ok"] and count_ok,
    }


def main(argv: list[str]) -> int:  # noqa: C901 (séquence linéaire lisible)
    args = [a for a in argv[1:] if a not in ("--write", "--keep")]
    write = "--write" in argv
    keep = "--keep" in argv  # ne pas purger (inspection visuelle périodique 5b)
    if not args:
        print(
            "usage: python run_replay.py <out_dir_hors_repo> [--write] [--keep] [phase]",
            file=sys.stderr,
        )
        return 2

    import os

    from audit_bim import config
    from audit_bim.mcp.security import set_runtime_transport

    set_runtime_transport("script")  # PR3 §3a — entrypoint local (writes/token permis)
    from audit_bim.mcp.tools_actions import (  # confirm gate (early-return)
        apply_bcf_topics,
        apply_smart_views_plan,
    )

    from audit_bim.actions.bcf_planner import apply_bcf, prepare_bcf
    from audit_bim.actions.plans import load_plan, save_plan
    from audit_bim.actions.smartview_planner import apply_smart_views, prepare_smart_views
    from audit_bim.audit.engine import run_audit
    from audit_bim.domain.filters import FindingFilter
    from audit_bim.extraction.client import BIMDataClient
    from audit_bim.extraction.model_data import extract_snapshot
    from audit_bim.requirements.catalog import build_catalog
    from audit_bim.requirements.models import BIMPhase
    from audit_bim.security.write_journal import get_journal

    out = Path(args[0])
    from audit_bim.security.guards import assert_outside_repo

    assert_outside_repo(out, context="a1-replay")
    out.mkdir(parents=True, exist_ok=True)
    os.environ["AUDIT_OUTPUT_DIR"] = str(out)  # plans scellés écrits hors repo
    phase = BIMPhase(args[1]) if len(args) > 1 else BIMPhase.AVP

    # 1. Cible explicite + contrôle d'identité par NOM EXACT.
    client = BIMDataClient()
    snap = extract_snapshot(client)
    model_name = (snap.model or {}).get("name") or ""
    if model_name.strip().casefold() != EXPECTED_MODEL_NAME.strip().casefold():
        raise SystemExit(
            f"REFUS : identité cible non conforme — modèle actif ≠ {EXPECTED_MODEL_NAME!r}."
        )
    effective_target = {
        "cloud_id": client.cloud_id,
        "project_id": client.project_id,
        "model_id": client.model_id,
    }

    # 3. Audit réel — vérifier d'ABORD la présence des documents I3F (refus
    # lisible AVANT build_catalog, qui tolère des documents absents).
    _docs = {
        "cch_pdf": config.I3F_CCH_PDF,
        "data_spec_xlsx": config.I3F_DATA_SPEC_XLSX,
        "naming_spec_xlsx": config.I3F_NAMING_SPEC_XLSX,
    }
    catalog = build_catalog(
        cch_pdf=config.I3F_CCH_PDF,
        data_spec_xlsx=config.I3F_DATA_SPEC_XLSX,
        naming_spec_xlsx=config.I3F_NAMING_SPEC_XLSX,
    )
    from audit_bim.security.guards import assert_catalog_usable

    assert_catalog_usable(_docs, catalog)
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

    # 6. Garde-fou négatif rejoué sur LES DEUX régimes : apply(confirm=False) → refus.
    neg_bcf = apply_bcf_topics(str(bcf_path), confirm=False)
    neg_sv = apply_smart_views_plan(str(sv_path), confirm=False)
    guardrail_ok = bool(neg_bcf.get("refused")) and bool(neg_sv.get("refused"))
    report["guardrail_confirm_false_refused"] = guardrail_ok
    if not guardrail_ok:
        raise SystemExit("REFUS : le garde-fou confirm=False n'a pas refusé — arrêt.")

    # 7. Apply confirm=True (chemin Python planner).
    bcf_res = apply_bcf(load_plan(bcf_path), client, actual_target=effective_target)
    sv_res = apply_smart_views(load_plan(sv_path), client, actual_target=effective_target)
    report["bcf_apply"] = {"succeeded": bcf_res.succeeded, "failed": bcf_res.failed}
    report["smart_views_apply"] = {"succeeded": sv_res.succeeded, "failed": sv_res.failed}

    # 9. Journal : relire audit_trail et vérifier que LES DEUX apply du run y
    #    figurent avec des compteurs conformes (indépendant du retour d'apply).
    journal = get_journal().tail(20)
    journal_bcf = journal_confirms(
        journal,
        action="apply_bcf_topics",
        plan_id=bcf_plan.plan_id,
        expected_succeeded=EXPECTED_BCF_TOPICS,
    )
    journal_sv = journal_confirms(
        journal,
        action="apply_smart_views",
        plan_id=sv_plan.plan_id,
        expected_succeeded=EXPECTED_SMART_VIEWS,
    )
    report["journal"] = {"bcf": journal_bcf, "smart_views": journal_sv}

    # 8. Vérification post-apply INDÉPENDANTE : relire via l'API (bimdata-read ≥
    #    0.1.1) les objets réellement créés et compter ceux au préfixe daté de CE
    #    run. C'est cette re-lecture qui ramène le hand-off 5b (vérif visuelle) à
    #    un contrôle **périodique** au lieu d'une étape obligatoire de chaque run.
    topics_bcf = client.list_bcf_topics()
    topics_sv = client.list_smart_views()
    api_bcf = verify_published(topics_bcf, title_prefix=prefix, expected_count=EXPECTED_BCF_TOPICS)
    api_sv = verify_published(topics_sv, title_prefix=prefix, expected_count=EXPECTED_SMART_VIEWS)
    report["api_verify"] = {"bcf": api_bcf, "smart_views": api_sv}

    write_ok = (
        bcf_res.succeeded == EXPECTED_BCF_TOPICS
        and bcf_res.failed == 0
        and sv_res.succeeded == EXPECTED_SMART_VIEWS
        and sv_res.failed == 0
        and journal_bcf
        and journal_sv
        and api_bcf["count_ok"]
        and api_sv["count_ok"]
    )

    # 10. Purge — supprimer les objets créés par CE run (préfixe daté) pour laisser
    #     la maquette jetable dans un état déterministe (re-run same-day propre).
    #     `--keep` saute la purge (inspection visuelle périodique 5b). La purge
    #     s'appuie sur les MÊMES listes déjà relues à l'étape 8, puis re-vérifie
    #     indépendamment qu'il ne reste plus rien au préfixe (compte attendu = 0).
    if keep:
        report["purge"] = {"skipped": True}
        purge_ok = True
    else:
        bcf_guids = select_purge_guids(topics_bcf, title_prefix=prefix)
        sv_guids = select_purge_guids(topics_sv, title_prefix=prefix)
        for g in bcf_guids:
            client.delete_bcf_topic(g)
        for g in sv_guids:
            client.delete_smart_view(g)
        after_bcf = verify_published(
            client.list_bcf_topics(), title_prefix=prefix, expected_count=0
        )
        after_sv = verify_published(
            client.list_smart_views(), title_prefix=prefix, expected_count=0
        )
        purge_ok = after_bcf["count_ok"] and after_sv["count_ok"]
        report["purge"] = {
            "deleted_bcf": len(bcf_guids),
            "deleted_smart_views": len(sv_guids),
            "bcf_clear": after_bcf["count_ok"],
            "smart_views_clear": after_sv["count_ok"],
            "ok": purge_ok,
        }

    # Verdict --write : écriture prouvée (3 niveaux) ET état laissé déterministe
    # (purge réussie, ou explicitement conservé via --keep).
    write_ok = write_ok and purge_ok
    report["verdict"] = "PASS" if write_ok else "FAIL"
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print("VERDICT:", report["verdict"])
    return 0 if write_ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
