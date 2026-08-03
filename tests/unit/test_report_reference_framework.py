"""Découplage du narratif : le référentiel vient du profil, plus du code.

`ReportProjectContext` portait `cch_version`, `cch_source` et `bim_reference` —
trois champs qui nommaient un maître d'ouvrage dans le contrat lui-même. Un
futur MCP AMO aurait hérité de « CCH BIM I3F » par construction.

Ces tests verrouillent les quatre exigences du découplage :

1. I3F imprime **exactement** le même texte qu'avant ;
2. un profil sans référentiel produit un contexte **sans aucune** trace I3F ;
3. le rendu n'accède plus aux champs plats hérités ;
4. la compatibilité legacy convertit au lieu d'avaler en silence.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from audit_bim.profiles import get_profile
from audit_bim.profiles.models import ReferenceFrameworkSpec
from audit_bim.reporting.context import (
    ReferenceFramework,
    ReportProjectContext,
    build_reference_framework,
)

REPORTING = Path(__file__).resolve().parents[2] / "audit_bim" / "reporting"


class _Catalog:
    """Double minimal de `RequirementsCatalog` (champs lus par le référentiel)."""

    def __init__(self, version="3.6", source="cch.pdf"):
        self.cch_version = version
        self.cch_source_pdf = source


# ── 1. I3F : texte strictement inchangé ───────────────────────────────


def test_i3f_label_reproduces_the_historical_string():
    fw = build_reference_framework(_Catalog())
    assert fw.label == "CCH BIM I3F V3.6"
    assert fw.name == "CCH BIM I3F"
    assert fw.short_name == "CCH"
    assert fw.long_name == "Cahier des Charges BIM I3F"
    assert fw.source == "cch.pdf"


def test_i3f_label_without_version_keeps_the_historical_fallback():
    assert build_reference_framework(_Catalog(version=None)).label == (
        "CCH BIM I3F (version non précisée)"
    )


def test_i3f_label_without_catalog_matches_the_no_version_case():
    assert build_reference_framework(None).label == "CCH BIM I3F (version non précisée)"


def test_long_form_reproduces_the_executive_summary_wording():
    """La synthèse imprimait « au Cahier des Charges BIM I3F V3.6 »."""
    from audit_bim.reporting.word_report import _framework_long_label

    ctx = ReportProjectContext(reference_framework=build_reference_framework(_Catalog()))
    assert _framework_long_label(ctx) == "Cahier des Charges BIM I3F V3.6"


# ── 2. Un profil sans référentiel n'hérite de rien ────────────────────

FORBIDDEN = ("I3F", "CCH", "Tarare", "0546L")


def test_profile_without_framework_produces_no_client_trace():
    fw = build_reference_framework(_Catalog(), profile_id="bim_in_motion")
    assert fw.label is None
    blob = fw.model_dump_json()
    for term in FORBIDDEN:
        assert term not in blob, f"{term!r} a fuité dans un profil sans référentiel"


def test_a_third_party_profile_prints_its_own_framework(monkeypatch):
    """Simule un profil AMO tiers : aucune occurrence I3F ne doit survivre."""
    from dataclasses import replace

    import audit_bim.profiles.registry as reg

    tiers = replace(
        reg._BIM_IN_MOTION_PROFILE,
        reference_framework=ReferenceFrameworkSpec(
            name="Référentiel AMO BIM in Motion",
            short_name="Référentiel",
            long_name="Référentiel AMO BIM in Motion",
        ),
    )
    monkeypatch.setattr(reg, "_PROFILES", (reg._I3F_PROFILE, tiers))

    fw = build_reference_framework(_Catalog(), profile_id="bim_in_motion")
    assert fw.label == "Référentiel AMO BIM in Motion V3.6"

    ctx = ReportProjectContext(reference_framework=fw, assumptions=[])
    blob = ctx.model_dump_json()
    for term in FORBIDDEN:
        assert term not in blob, f"{term!r} imprimé pour un AMO tiers"


def test_i3f_profile_still_declares_its_framework():
    spec = get_profile("i3f").reference_framework
    assert spec is not None and spec.name == "CCH BIM I3F"


# ── 3. Le rendu n'accède plus aux champs plats hérités ────────────────


@pytest.mark.parametrize("module", ["word_report.py", "xlsx_annex.py", "context.py"])
def test_rendering_modules_never_read_legacy_flat_fields(module):
    """Aucun accès `<qqch>.cch_version` / `.cch_source` / `.bim_reference`.

    L'exception est `catalog.cch_*` : le catalogue d'exigences reste un objet
    I3F légitime, seul le *contexte de rapport* devait être neutralisé.
    """
    tree = ast.parse((REPORTING / module).read_text(encoding="utf-8"))
    offenders = [
        f"{node.value.id if isinstance(node.value, ast.Name) else '?'}.{node.attr}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and node.attr in {"cch_version", "cch_source", "bim_reference"}
        and not (isinstance(node.value, ast.Name) and node.value.id == "catalog")
    ]
    assert not offenders, f"{module} lit encore des champs hérités : {offenders}"


def test_no_hardcoded_client_framework_in_neutral_reporting():
    """Garde-fou statique : « CCH BIM I3F » interdit dans le socle narratif.

    Les règles et exigences I3F ont parfaitement le droit de citer le CCH ;
    les modules de rendu, non — ce sont eux qui partiront dans `bim-reporting`.
    """
    neutral = ["context.py", "word_report.py", "xlsx_annex.py", "theming.py", "pdf_export.py"]
    offenders = []
    for name in neutral:
        for lineno, line in enumerate(
            (REPORTING / name).read_text(encoding="utf-8").splitlines(), 1
        ):
            if re.search(r"CCH\s+BIM\s+I3F", line) or re.search(
                r"\bTarare\b|\b0546L\b", line, re.I
            ):
                offenders.append(f"{name}:{lineno}")
    assert not offenders, f"référentiel client écrit en dur dans le socle narratif : {offenders}"


def test_static_guard_is_not_vacuous(tmp_path):
    """Le garde-fou doit savoir rougir."""
    bad = tmp_path / "bad.py"
    bad.write_text('label = "CCH BIM I3F V3.6"\n', encoding="utf-8")
    assert re.search(r"CCH\s+BIM\s+I3F", bad.read_text(encoding="utf-8"))


# ── 4. Compatibilité legacy : convertir, jamais avaler ────────────────


def test_legacy_flat_fields_are_converted():
    ctx = ReportProjectContext(
        cch_version="3.6", cch_source="x.pdf", bim_reference="CCH BIM I3F V3.6"
    )
    fw = ctx.reference_framework
    assert (fw.name, fw.version, fw.source) == ("CCH BIM I3F", "3.6", "x.pdf")
    assert fw.label == "CCH BIM I3F V3.6"


def test_legacy_reference_without_version_is_parsed():
    ctx = ReportProjectContext(bim_reference="CCH BIM I3F (version non précisée)")
    assert ctx.reference_framework.name == "CCH BIM I3F"


def test_legacy_read_properties_still_answer():
    ctx = ReportProjectContext(cch_version="3.6", bim_reference="CCH BIM I3F V3.6")
    assert ctx.cch_version == "3.6"
    assert ctx.bim_reference == "CCH BIM I3F V3.6"
    assert ctx.cch_source is None


def test_neutral_model_wins_over_legacy_input():
    """La compat ne remplit que les trous — elle n'écrase jamais le neutre."""
    ctx = ReportProjectContext(
        reference_framework=ReferenceFramework(name="Neutre", version="9"),
        cch_version="3.6",
        bim_reference="CCH BIM I3F V3.6",
    )
    assert ctx.reference_framework.name == "Neutre"
    assert ctx.reference_framework.version == "9"


def test_context_without_any_reference_is_empty_not_i3f():
    """Le défaut est vide, jamais un référentiel hérité."""
    fw = ReportProjectContext().reference_framework
    assert fw.label is None and fw.name is None


# ── 5. Bout en bout : un profil tiers produit un contexte sans I3F ────


def test_end_to_end_context_for_a_third_party_profile_has_no_i3f(
    catalog, snapshot_minimal, monkeypatch
):
    """Le vrai critère : `build_report_context` complet, profil tiers, zéro I3F.

    Les tests précédents portent sur le modèle ; celui-ci exerce la chaîne
    entière — hypothèses, contrôles réalisés, sources — là où le vocabulaire
    client se glissait auparavant en dur.
    """
    from dataclasses import replace

    import audit_bim.profiles.registry as reg
    from audit_bim.audit.engine import AuditResult
    from audit_bim.reporting.context import build_report_context
    from audit_bim.requirements.models import BIMPhase

    tiers = replace(
        reg._BIM_IN_MOTION_PROFILE,
        reference_framework=ReferenceFrameworkSpec(
            name="Référentiel AMO BIM in Motion",
            short_name="Référentiel",
            long_name="Référentiel AMO BIM in Motion",
        ),
    )
    monkeypatch.setattr(reg, "_PROFILES", (reg._I3F_PROFILE, tiers))

    result = AuditResult(
        snapshot=snapshot_minimal, catalog=catalog, phase=BIMPhase.PRO, findings=[]
    )
    ctx = build_report_context(result, profile_id="bim_in_motion")

    assert ctx.reference_framework.name == "Référentiel AMO BIM in Motion"
    blob = ctx.model_dump_json()
    for term in ("I3F", "CCH BIM", "Tarare", "0546L"):
        assert term not in blob, f"{term!r} imprimé dans le contexte d'un AMO tiers"


def test_end_to_end_context_for_i3f_is_unchanged(catalog, snapshot_minimal):
    """Même chaîne, profil I3F : le libellé historique doit réapparaître."""
    from audit_bim.audit.engine import AuditResult
    from audit_bim.reporting.context import build_report_context
    from audit_bim.requirements.models import BIMPhase

    result = AuditResult(
        snapshot=snapshot_minimal, catalog=catalog, phase=BIMPhase.PRO, findings=[]
    )
    ctx = build_report_context(result)
    assert ctx.reference_framework.label == f"CCH BIM I3F V{catalog.cch_version}"
    assert any("CCH BIM I3F" in a for a in ctx.assumptions)


# ── 6. Instantané des chaînes I3F : la dérive doit rougir ─────────────

#: Chaînes exactes produites pour I3F **avant** le découplage. Figées ici parce
#: qu'un paramétrage plausible peut les changer sans rien casser d'autre : en
#: câblant cette PR, `short_name` ("CCH") a d'abord remplacé "I3F" dans
#: « codification I3F » — la phrase cite le maître d'ouvrage, pas le document.
#: Aucun autre test ne l'aurait vu.
I3F_CONTROL_STRINGS = {
    "rule_sources": [
        "CCH BIM I3F V3.6, chapitre 6.1",
        "Annexe « Nommage » (XLSX)",
        "CCH BIM I3F V3.6, chapitre 6.4",
        "Annexe « Spécifications » (XLSX)",
        "CCH BIM I3F V3.6, chapitre 6.2",
        "Annexe « Nommage » + programme MOA",
        "MVD IFC + CCH BIM I3F",
    ],
    "naming_objective": (
        "Conformité aux conventions de codification I3F et aux listes fermées d'étages et de zones."
    ),
}


def test_i3f_control_strings_are_byte_identical():
    from audit_bim.reporting.context import _build_controls_performed

    controls = _build_controls_performed(_Catalog())
    assert [c.rule_source for c in controls] == I3F_CONTROL_STRINGS["rule_sources"]
    naming = next(c for c in controls if c.theme.startswith("Nommage Site"))
    assert naming.objective == I3F_CONTROL_STRINGS["naming_objective"]


def test_i3f_assumption_sentence_is_byte_identical(catalog, snapshot_minimal):
    from audit_bim.audit.engine import AuditResult
    from audit_bim.reporting.context import build_report_context
    from audit_bim.requirements.models import BIMPhase

    assert catalog.cch_version == "3.6", "fixture attendue en CCH 3.6"
    result = AuditResult(
        snapshot=snapshot_minimal, catalog=catalog, phase=BIMPhase.PRO, findings=[]
    )
    ctx = build_report_context(result)
    assert (
        "Les exigences sont interprétées selon la version 3.6 "
        "du CCH BIM I3F transmise au moment de l'audit."
    ) in ctx.assumptions
