"""Couverture Domofrance × spatial_evidence/v1 — évaluabilité, pas conformité.

Point d'entrée CLI. La logique vit dans
:mod:`audit_bim.profiles.domofrance.coverage` ; ce fichier n'analyse que
``argv``.

Croise la liste de contrôle du maître d'ouvrage (Domo-0) avec un document de
preuves géométriques réellement produit, et dit pour chaque contrôle **s'il
pourra être tranché**, jamais s'il est conforme. Aucun statut de conformité
n'est calculé, aucune maquette n'est jugée.

Un contrôle n'est déclaré évaluable que si une **règle explicite du registre**
le revendique **et** que le champ visé est **effectivement renseigné** dans le
document fourni. Cf. ``docs/scope-domofrance-coverage.md``.

Usage::

    python scripts/coverage_domofrance_controls.py <Liste de contrôle.xlsx> \
        <maquette_spatial_evidence.json>
    ... --csv > couverture.csv
"""

from __future__ import annotations

import sys


def main(argv: list[str]) -> int:
    if len(argv) < 3 or argv[1] in frozenset({"--help", "-h"}):
        print(__doc__)
        return 0

    from audit_bim.profiles.domofrance.controls import parse_controls, parse_surface_tables
    from audit_bim.profiles.domofrance.coverage import (
        assess,
        print_csv,
        print_report,
        read_evidence,
    )

    controls = parse_controls(argv[1])
    facts = read_evidence(argv[2])
    assessments = [assess(c, facts) for c in controls]
    if "--csv" in argv[3:]:
        print_csv(assessments)
        return 0
    print_report(assessments, facts, parse_surface_tables(argv[1]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
