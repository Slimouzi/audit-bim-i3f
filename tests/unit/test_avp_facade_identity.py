"""Gate d'identité : ``audit_bim.reporting.avp_i3f`` est une **façade** au-dessus
du package interne ``audit_bim.reporting.avp``.

Le découpage du reporting AVP (PR 2) ne doit rien changer d'observable :

- les imports historiques restent valides et pointent vers *les mêmes objets*
  (aucune logique dupliquée entre la façade et le package) ;
- la façade reste **courte** (ré-exports + docstring, aucune implémentation) ;
- les noms de fichiers livrables sont inchangés.
"""

from __future__ import annotations

import ast
from pathlib import Path

from audit_bim.reporting import avp_i3f
from audit_bim.reporting.avp import models as avp_models
from audit_bim.reporting.avp import pack as avp_pack
from audit_bim.reporting.avp import xlsx_common, xlsx_controle, xlsx_enveloppe

# ── Anciens imports toujours valides ───────────────────────────────────


def test_legacy_public_imports_still_work():
    """Les imports publics historiques restent importables depuis la façade."""
    from audit_bim.reporting.avp_i3f import (  # noqa: F401
        NOT_AVAILABLE,
        AvpMeta,
        AvpQaError,
        AvpReportPack,
        build_sources_from_snapshot,
        write_avp_i3f_report_pack,
    )


def test_facade_symbols_are_the_package_objects():
    """Ré-export = même objet (pas de copie / réimplémentation)."""
    assert avp_i3f.write_avp_i3f_report_pack is avp_pack.write_avp_i3f_report_pack
    assert avp_i3f.AvpMeta is avp_models.AvpMeta
    assert avp_i3f.AvpReportPack is avp_models.AvpReportPack
    assert avp_i3f.AvpQaError is avp_models.AvpQaError


def test_legacy_private_patch_points_still_exposed():
    """Points d'entrée privés utilisés par les tests historiques : intacts."""
    assert avp_i3f._audit_stats is xlsx_controle._audit_stats
    assert avp_i3f._count_controle_rows is xlsx_controle._count_controle_rows
    assert avp_i3f._zone_finding_kind is xlsx_controle._zone_finding_kind
    assert avp_i3f._count_business_rows is xlsx_common._count_business_rows
    assert avp_i3f._build_enveloppe_xlsx is xlsx_enveloppe._build_enveloppe_xlsx


def test_all_exports_are_resolvable():
    for name in avp_i3f.__all__:
        assert hasattr(avp_i3f, name), name


# ── La façade ne porte plus d'implémentation ───────────────────────────


def test_facade_module_is_short_and_logic_free():
    """Garde-fou anti-regrowth : la façade ne doit pas redevenir un monolithe."""
    src = Path(avp_i3f.__file__).read_text(encoding="utf-8")
    assert len(src.splitlines()) < 120

    tree = ast.parse(src)
    defined = [
        n.name
        for n in tree.body
        if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
    ]
    assert defined == [], f"logique résiduelle dans la façade : {defined}"


# ── Noms de livrables inchangés ────────────────────────────────────────


def test_deliverable_filenames_unchanged():
    """Convention I3F ``YYMMDD Nom Code Phase - TypeLivrable.ext`` (7 livrables)."""
    kwargs = {
        "date": "260702",
        "project_name": "Tarare",
        "project_code": "0546L",
        "phase": "AVP",
    }
    assert {
        key: avp_models._deliverable_filename(key, **kwargs)
        for key in avp_models._DELIVERABLE_LABELS
    } == {
        "controle": "260702 Tarare 0546L AVP - Contrôle Maquettes.xlsx",
        "shab": "260702 Tarare 0546L AVP - export SHAB maquette.xlsx",
        "zones_espaces": "260702 Tarare 0546L AVP - Export Zones et Espaces.xlsx",
        "enveloppe": "260702 Tarare 0546L AVP - Extraction surface enveloppe.xlsx",
        "menuiseries": "260702 Tarare 0546L AVP - export Menuiseries.xlsx",
        "plancher": "260702 Tarare 0546L AVP - export plancher.xlsx",
        "analyse": "260702 Tarare 0546L AVP - Rapport analyse BIM.docx",
    }
