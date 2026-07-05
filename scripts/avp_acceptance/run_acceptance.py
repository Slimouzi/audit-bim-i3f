"""Acceptation RÉELLE du pack AVP sur une vraie maquette BIMData.

Génère le pack AVP depuis un modèle BIMData réel (config via l'environnement),
puis vérifie que **les 5 annexes** sont non vides et **habillées de la charte
BIMData**. **Read-only côté BIMData** (extraction seule ; aucune écriture, aucune
publication).

⚠️ Le pack généré (xlsx/docx) contient des **données client** : il ne doit JAMAIS
être versionné. Le script **refuse** d'écrire dans le dépôt — passe un dossier de
sortie **hors du repo** (ex. ``/tmp/avp-acceptance``). La sortie stdout ne contient
QUE des compteurs, des booléens et un verdict (aucune donnée client).

Usage: python run_acceptance.py <out_dir_hors_repo> [phase]
"""

from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path


def _assert_outside_repo(out: Path) -> None:
    root = Path(__file__).resolve()
    while root != root.parent and not (root / ".git").exists():
        root = root.parent
    out = out.resolve()
    if out == root or root in out.parents:
        raise SystemExit(
            f"REFUS : {out} est dans le dépôt {root}. Le pack contient des données "
            f"client — écris-le HORS du repo (ex. /tmp/avp-acceptance)."
        )


def assert_catalog_usable(docs: dict[str, str | None], catalog) -> None:
    """Refuse un référentiel CCH inexploitable — **helper pur, testable**.

    ``build_catalog`` tolère des documents absents et rend un catalogue
    partiel/vide ; sans contrôle, l'acceptation pourrait rendre ``PASS`` sans
    aucun référentiel CCH réellement chargé. On refuse (``SystemExit``) si :

    - un des documents I3F (``docs`` = nom → chemin) est absent/introuvable ;
    - ``catalog.properties`` ou ``catalog.naming_rules`` est vide.
    """
    missing = [name for name, p in docs.items() if not p or not Path(p).exists()]
    if missing:
        raise SystemExit(f"REFUS : documents I3F absents {missing} — contrôle CCH impossible.")
    n_props = len(getattr(catalog, "properties", None) or [])
    n_rules = len(getattr(catalog, "naming_rules", None) or [])
    if n_props == 0 or n_rules == 0:
        raise SystemExit(
            f"REFUS : catalogue CCH vide (properties={n_props}, naming_rules={n_rules}) "
            f"— acceptation non fiable."
        )


def _charte_flags(path: Path, wordmark: str, primary: str, font: str) -> dict:
    with zipfile.ZipFile(path) as z:
        blob = b"".join(z.read(n) for n in z.namelist() if n.endswith((".xml", ".rels"))).upper()
    return {
        "wordmark": wordmark.encode().upper() in blob,
        "primary": primary.encode().upper() in blob,
        "font": font.encode().upper() in blob,
        "no_korhus": b"KORHUS" not in blob,
    }


def main(argv: list[str]) -> int:
    if len(argv) not in (2, 3):
        print("usage: python run_acceptance.py <out_dir_hors_repo> [phase]", file=sys.stderr)
        return 2

    from audit_bim import config
    from audit_bim.audit.engine import run_audit
    from audit_bim.extraction.client import BIMDataClient
    from audit_bim.extraction.model_data import extract_snapshot
    from audit_bim.reporting.avp_i3f import (
        _count_business_rows,
        _count_controle_rows,
        write_avp_i3f_report_pack,
    )
    from audit_bim.reporting.bimdata_brand import WORDMARK
    from audit_bim.reporting.theming import BIMDATA_FONT_PRIMARY, BIMDATA_PRIMARY
    from audit_bim.requirements.catalog import build_catalog
    from audit_bim.requirements.models import BIMPhase

    out = Path(argv[1])
    _assert_outside_repo(out)
    out.mkdir(parents=True, exist_ok=True)
    phase = BIMPhase(argv[2]) if len(argv) == 3 else BIMPhase.AVP

    catalog = build_catalog(
        cch_pdf=config.I3F_CCH_PDF,
        data_spec_xlsx=config.I3F_DATA_SPEC_XLSX,
        naming_spec_xlsx=config.I3F_NAMING_SPEC_XLSX,
    )
    # Garde CCH (helper pur, testé) : refuse un référentiel inexploitable.
    assert_catalog_usable(
        {
            "cch_pdf": config.I3F_CCH_PDF,
            "data_spec_xlsx": config.I3F_DATA_SPEC_XLSX,
            "naming_spec_xlsx": config.I3F_NAMING_SPEC_XLSX,
        },
        catalog,
    )

    client = BIMDataClient()  # cible + auth depuis l'environnement (read-only)
    snap = extract_snapshot(client)
    result = run_audit(snap, catalog, phase)

    pack = write_avp_i3f_report_pack(
        result,
        out,
        sources=None,  # chemin réel piloté par la maquette
        project_name=(snap.project or {}).get("name") or "ACCEPTANCE",
        project_code="",
        phase=phase.value,
        export_pdf=False,
    )

    annexes = {
        "Contrôle": pack.controle_xlsx,
        "SHAB": pack.shab_xlsx,
        "Zones/Espaces": pack.zones_espaces_xlsx,
        "Enveloppe": pack.enveloppe_xlsx,
        "Menuiseries": pack.menuiseries_xlsx,
    }

    # Confidentialité : la sortie stdout ne porte AUCUNE donnée client (pas de
    # nom de modèle/projet). Uniquement phase, compteurs, booléens de charte,
    # verdict. Le pack complet (données client) reste hors repo.
    report: dict = {"phase": phase.value, "annexes": {}}
    ok = True
    for label, p in annexes.items():
        # Contrôle : compteur propre (points de contrôle sous la grille, hors
        # entête/légende/NOT_AVAILABLE) ; les 4 autres : compteur générique.
        rows = _count_controle_rows(p) if label == "Contrôle" else _count_business_rows(p)
        charte = _charte_flags(p, WORDMARK, BIMDATA_PRIMARY, BIMDATA_FONT_PRIMARY)
        entry = {"rows": rows, "non_empty": rows > 0, **charte}
        report["annexes"][label] = entry
        ok = ok and entry["non_empty"] and all(charte.values())

    report["verdict"] = "PASS" if ok else "FAIL"
    # Sortie sûre : compteurs / booléens / verdict uniquement.
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print("VERDICT:", report["verdict"])
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
