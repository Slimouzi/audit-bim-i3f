"""Interface en ligne de commande : ``audit-bim`` (équivalent CLI du tool MCP).

Permet de lancer un audit complet sans démarrer le serveur MCP — utile pour
batch / CI / scripts d'investigation.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import config
from .audit.engine import run_audit
from .bcf.builder import push_bcf_topics
from .extraction.client import BIMDataClient
from .extraction.model_data import extract_snapshot
from .reporting.word_report import write_word_report
from .reporting.xlsx_annex import write_xlsx_annex
from .requirements.catalog import build_catalog
from .requirements.models import BIMPhase
from .smartview.builder import push_smart_views

PUSH_MODES = ("ask", "bcf", "smartview", "both", "none")


def _prompt_push_mode() -> str:
    """Demande interactive si ``--push`` vaut ``ask``. Retourne le mode choisi."""
    print(
        "\nComment publier les résultats dans le viewer BIMData ?\n"
        "  bcf       — BCF Topics (workflow d'issues à résoudre)\n"
        "  smartview — Smart Views (vues 3D colorées, panneau dédié)\n"
        "  both      — Les deux\n"
        "  none      — Ne rien publier (payloads sauvegardés en JSON)\n",
        file=sys.stderr,
    )
    while True:
        choice = input("Choix [bcf/smartview/both/none] : ").strip().lower()
        if choice in ("bcf", "smartview", "both", "none"):
            return choice
        print("Valeur invalide, recommencer.", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="audit-bim",
        description=(
            "Audit BIM I3F : génère rapport Word + annexe XLSX et publie "
            "vers BIMData (BCF Topics et/ou Smart Views)."
        ),
    )
    parser.add_argument("--cch-pdf", default=config.I3F_CCH_PDF)
    parser.add_argument("--data-spec", default=config.I3F_DATA_SPEC_XLSX)
    parser.add_argument("--naming-spec", default=config.I3F_NAMING_SPEC_XLSX)
    parser.add_argument("--cloud-id", default=config.CLOUD_ID)
    parser.add_argument("--project-id", default=config.PROJECT_ID)
    parser.add_argument("--model-id", default=config.MODEL_ID)
    parser.add_argument(
        "--phase",
        default="PRO",
        choices=[p.value for p in BIMPhase.ordered()],
    )
    parser.add_argument("--out-dir", default=str(config.AUDIT_OUTPUT_DIR))
    parser.add_argument(
        "--push",
        default="ask",
        choices=list(PUSH_MODES),
        help=(
            "Mode de publication des résultats : "
            "'bcf' (issues à résoudre), 'smartview' (vues 3D), "
            "'both' (les deux), 'none' (rien). Par défaut 'ask' = "
            "demande interactive."
        ),
    )
    parser.add_argument(
        "--access-token",
        default=None,
        help=(
            "Bearer token BIMData déjà acquis (sinon API key / OAuth "
            "client_credentials via .env)."
        ),
    )
    # Rétrocompat : ancien flag --push-smart-views
    parser.add_argument(
        "--push-smart-views",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args()

    # Rétrocompat : --push-smart-views (legacy) → --push smartview
    push_mode = args.push
    if args.push_smart_views and push_mode == "ask":
        push_mode = "smartview"
    if push_mode == "ask":
        push_mode = _prompt_push_mode()

    print(">> Catalogue d'exigences", file=sys.stderr)
    catalog = build_catalog(
        cch_pdf=args.cch_pdf,
        data_spec_xlsx=args.data_spec,
        naming_spec_xlsx=args.naming_spec,
    )
    print(json.dumps(catalog.summary(), ensure_ascii=False, indent=2), file=sys.stderr)

    print(">> Connexion BIMData & snapshot du modèle", file=sys.stderr)
    client = BIMDataClient(
        cloud_id=args.cloud_id,
        project_id=args.project_id,
        model_id=args.model_id,
        access_token=args.access_token,
    )
    snap = extract_snapshot(client)
    print(json.dumps(snap.summary(), ensure_ascii=False, indent=2), file=sys.stderr)

    phase = BIMPhase(args.phase)
    print(f">> Audit phase {phase.value}", file=sys.stderr)
    result = run_audit(snap, catalog, phase)
    print(json.dumps(result.summary(), ensure_ascii=False, indent=2), file=sys.stderr)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    from datetime import datetime

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = "".join(
        c
        for c in (snap.project or {}).get("name", args.project_id or "projet")
        if c not in r'\/:*?"<>|'
    ).strip()
    base = out_dir / f"audit_{safe_name}_{phase.value}_{ts}"
    word_path = Path(f"{base}.docx")
    xlsx_path = Path(f"{base}_annexes.xlsx")

    print(">> XLSX annexe", file=sys.stderr)
    write_xlsx_annex(result, xlsx_path)
    print(">> Rapport Word", file=sys.stderr)
    write_word_report(result, word_path, xlsx_annex_path=xlsx_path)

    do_bcf = push_mode in ("bcf", "both")
    do_sv = push_mode in ("smartview", "both")

    print(
        f">> Publication : BCF Topics (dry_run={not do_bcf}) — "
        f"Smart Views (dry_run={not do_sv})",
        file=sys.stderr,
    )
    bcf_res = push_bcf_topics(result, client, dry_run=not do_bcf)
    sv_res = push_smart_views(result, client, dry_run=not do_sv)

    Path(f"{base}_bcf_topics.json").write_text(
        json.dumps(bcf_res, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    Path(f"{base}_smart_views.json").write_text(
        json.dumps(sv_res, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    Path(f"{base}_findings.json").write_text(
        json.dumps(
            [f.model_dump(mode="json") for f in result.findings],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print("\n>> Livrables :", file=sys.stderr)
    for p in (
        word_path,
        xlsx_path,
        Path(f"{base}_findings.json"),
        Path(f"{base}_bcf_topics.json"),
        Path(f"{base}_smart_views.json"),
    ):
        print(f"   • {p}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
