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
from .actions import prepare_bcf, prepare_smart_views, save_plan
from .audit.engine import run_audit
from .extraction.client import BIMDataClient
from .extraction.model_data import extract_snapshot
from .reporting.word_report import write_word_report
from .reporting.xlsx_annex import write_xlsx_annex
from .requirements.catalog import build_catalog
from .requirements.models import BIMPhase

PUSH_MODES = ("ask", "bcf", "smartview", "both", "none")


def _prompt_push_mode() -> str:
    """Demande interactive si ``--push`` vaut ``ask``. Retourne le mode choisi."""
    print(
        "\nQuels plans de publication préparer ? (la CLI n'écrit jamais dans "
        "BIMData — elle prépare des plans scellés ; l'écriture se fait ensuite "
        "via le serveur MCP apply_* avec confirm=True après revue.)\n"
        "  bcf       — Plan BCF Topics (panneau BCF Issues)\n"
        "  smartview — Plan Smart Views (panneau dédié)\n"
        "  both      — Les deux plans\n"
        "  none      — Ne préparer aucun plan de publication\n",
        file=sys.stderr,
    )
    while True:
        choice = input("Choix [bcf/smartview/both/none] : ").strip().lower()
        if choice in ("bcf", "smartview", "both", "none"):
            return choice
        print("Valeur invalide, recommencer.", file=sys.stderr)


def main() -> int:
    from audit_bim.mcp.security import set_runtime_transport

    set_runtime_transport("script")  # PR3 §3a — CLI = entrypoint local
    parser = argparse.ArgumentParser(
        prog="audit-bim",
        description=(
            "Audit BIM I3F : génère rapport Word + annexe XLSX et **prépare** "
            "des plans de publication BIMData (BCF Topics et/ou Smart Views). "
            "N'écrit jamais dans BIMData — la publication se fait via le serveur "
            "MCP apply_* après revue."
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
            "Plans de publication à préparer (aucune écriture) : "
            "'bcf' (BCF Topics), 'smartview' (Smart Views), "
            "'both' (les deux), 'none' (aucun). Par défaut 'ask' = "
            "demande interactive."
        ),
    )
    parser.add_argument(
        "--access-token",
        default=None,
        help=(
            "Bearer token BIMData déjà acquis (sinon API key / OAuth client_credentials via .env)."
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

    # Publication — **préparation de plans uniquement**. La CLI n'écrit jamais
    # dans BIMData (aucun appel ``push_*`` direct) : elle prépare des ``WritePlan``
    # scellés. La publication passe ensuite par le serveur MCP
    # ``apply_bcf_topics`` / ``apply_smart_views_plan`` (confirm=True) après revue.
    do_bcf = push_mode in ("bcf", "both")
    do_sv = push_mode in ("smartview", "both")
    # Cible **effective** issue du client (résout le fallback ``.env`` /
    # normalisation), pas des arguments bruts — sinon le plan pourrait être
    # scellé sur une cible différente de celle réellement extraite.
    target = {
        "cloud_id": client.cloud_id,
        "project_id": client.project_id,
        "model_id": client.model_id,
        "model_name": (snap.model or {}).get("name"),
    }
    prepared: list[Path] = []
    if do_bcf:
        bcf_path = save_plan(prepare_bcf(result, target=target))
        prepared.append(bcf_path)
        print(f">> Plan BCF préparé (aucune écriture) : {bcf_path}", file=sys.stderr)
    if do_sv:
        sv_path = save_plan(prepare_smart_views(result, target=target))
        prepared.append(sv_path)
        print(f">> Plan Smart Views préparé (aucune écriture) : {sv_path}", file=sys.stderr)

    findings_path = Path(f"{base}_findings.json")
    findings_path.write_text(
        json.dumps(
            [f.model_dump(mode="json") for f in result.findings],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print("\n>> Livrables :", file=sys.stderr)
    for p in (word_path, xlsx_path, findings_path, *prepared):
        print(f"   • {p}", file=sys.stderr)
    if prepared:
        print(
            "\n>> Publication : plans préparés (aucune écriture). Pour publier, "
            "revoir chaque plan puis, côté serveur MCP, "
            "apply_bcf_topics / apply_smart_views_plan(plan_path=..., confirm=True).",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
