#!/usr/bin/env python
"""Diagnostic des Psets MRN manquants sur une maquette BIMData.

Sépare les exigences bloquées en deux populations : Pset non saisi, et Pset
peut-être équivalent sous un autre nom. Ne propose aucun mapping validé.

Usage::

    python scripts/inventory_mrn_pset_gap.py <table_attributs.xlsx> <url_viewer>
"""

from __future__ import annotations

import sys


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2

    from audit_bim.extraction.model_data import extract_snapshot
    from audit_bim.mcp.session import _State
    from audit_bim.profiles.bim_in_motion.mrn import parse_mrn_attribute_table
    from audit_bim.profiles.bim_in_motion.mrn.coverage import assess_mrn_coverage
    from audit_bim.profiles.bim_in_motion.mrn.pset_gap import diagnose_pset_gap
    from audit_bim.profiles.bim_in_motion.tools_session import set_active_target

    requirements = parse_mrn_attribute_table(argv[1]).requirements
    set_active_target(bimdata_url=argv[2])
    snapshot = extract_snapshot(_State.client)

    coverage = assess_mrn_coverage(requirements, snapshot)
    blocked = [c for c in coverage.requirements if c.status == "non_evaluable_mapping_pset"]
    by_property = {(r.sheet, r.row): r.property_name for r in requirements}
    for entry in blocked:
        entry_property = by_property.get((entry.sheet, entry.row), "")
        object.__setattr__(entry, "property_name", entry.property_name or entry_property)

    gaps = diagnose_pset_gap(blocked, snapshot)

    # Compte par EXIGENCE, jamais par groupe. Le calcul vit dans `pset_gap`
    # (`covered_rows`, teste sur le cas IfcWindow) : le reimplementer ici a
    # produit 54 au lieu de 21, et c'est le script qu'on execute.
    covered = {key for gap in gaps for key in gap.covered_rows}

    print(f"exigences bloquées                              : {len(blocked)}")
    print(f"  propriété exacte retrouvée (classe compatible) : {len(covered)}")
    print(f"  aucun candidat exact                           : {len(blocked) - len(covered)}")
    print()
    print("par Pset attendu — exigences couvertes / total :")
    per_pset: dict[str, list[int]] = {}
    for entry in blocked:
        bucket = per_pset.setdefault(entry.pset, [0, 0])
        bucket[1] += 1
        if (entry.sheet, entry.row) in covered:
            bucket[0] += 1
    for pset, (hit, total) in sorted(per_pset.items(), key=lambda kv: -kv[1][1]):
        print(f"  {pset:38} {hit:4} / {total:<4}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
