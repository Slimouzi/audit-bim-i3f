"""Extrait UNE FOIS un snapshot + catalogue I3F réels et les sérialise.

Ces artefacts alimentent ensuite les deux versions du moteur (ancien commit vs
façade) à l'identique — cf. ``replay.py`` puis ``compare.py``. **Read-only** :
aucune écriture BIMData.

⚠️ Les fichiers produits (``snapshot.json``, ``catalog.json``) contiennent des
**données client** : ils ne doivent JAMAIS être versionnés. Ce script **refuse**
d'écrire à l'intérieur du dépôt (garde ci-dessous) — passe un dossier de sortie
**hors du repo** (ex. ``/tmp/engine-parity``).

Usage: python extract_artifacts.py <out_dir_hors_repo>
Configuration BIMData via l'environnement (.env) : BIMDATA_API_KEY,
BIMDATA_CLOUD_ID, BIMDATA_PROJECT_ID, BIMDATA_MODEL_ID, BIMDATA_BASE_URL…
"""

from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python extract_artifacts.py <out_dir_hors_repo>", file=sys.stderr)
        return 2

    # Imports tardifs : ne charger audit_bim qu'après la validation des args.
    from audit_bim.extraction.client import BIMDataClient
    from audit_bim.mcp.security import set_runtime_transport

    set_runtime_transport("script")  # PR3 §3a — entrypoint local (writes/token permis)
    from audit_bim.extraction.model_data import extract_snapshot
    from audit_bim.requirements.catalog import build_catalog

    out = Path(argv[1])
    from audit_bim.security.guards import assert_outside_repo

    assert_outside_repo(out, context="engine-parity")
    out.mkdir(parents=True, exist_ok=True)

    # Documents MOA : chemins via l'environnement (config), pas de valeur en dur.
    from audit_bim import config

    catalog = build_catalog(
        cch_pdf=config.I3F_CCH_PDF,
        data_spec_xlsx=config.I3F_DATA_SPEC_XLSX,
        naming_spec_xlsx=config.I3F_NAMING_SPEC_XLSX,
    )
    (out / "catalog.json").write_text(catalog.model_dump_json())

    client = BIMDataClient()  # cible + auth depuis l'environnement
    snap = extract_snapshot(client)
    (out / "snapshot.json").write_text(json.dumps(dataclasses.asdict(snap)))

    # Résumés uniquement (compteurs) — pas de dump de contenu ici.
    print("CATALOG:", json.dumps(catalog.summary(), ensure_ascii=False))
    print("SNAPSHOT:", json.dumps(snap.summary(), ensure_ascii=False))
    print("OK artifacts ->", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
