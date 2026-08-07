"""Inventaire de la liste de contrôle Domofrance — description, pas conformité.

Point d'entrée CLI. La logique vit dans
:mod:`audit_bim.profiles.domofrance.controls` ; ce fichier n'analyse que
``argv``.

Ce script **décrit** le classeur du maître d'ouvrage. Il ne lit aucune maquette,
n'émet aucun statut de conformité, et ne dit jamais qu'un contrôle est
« évaluable » : ce verdict-là suppose une preuve géométrique (cf.
``docs/scope-domofrance-controls.md``).

Deux sorties :

- ``--summary`` (défaut) : les compteurs figés dans le scope, tous mesurés ici.
- ``--csv`` : une ligne par contrôle, avec sa ligne source et ses signaux
  lexicaux, pour relecture humaine.

Usage::

    python scripts/inventory_domofrance_controls.py <Liste de contrôle.xlsx>
    python scripts/inventory_domofrance_controls.py <fichier.xlsx> --csv > out.csv
"""

from __future__ import annotations

import sys


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] in frozenset({"--help", "-h"}):
        print(__doc__)
        return 0

    from audit_bim.profiles.domofrance.controls import (
        parse_controls,
        parse_surface_tables,
        print_csv,
        print_summary,
    )

    path = argv[1]
    controls = parse_controls(path)
    if len(argv) > 2 and argv[2] == "--csv":
        print_csv(controls)
        return 0
    print_summary(controls, parse_surface_tables(path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
