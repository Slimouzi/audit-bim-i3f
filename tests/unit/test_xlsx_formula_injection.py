"""Tests anti-injection de formule sur l'annexe XLSX."""

from __future__ import annotations

from audit_bim.reporting.xlsx_annex import _fmt_cell, _neutralize_formula


class TestNeutralizeFormula:
    def test_equals_prefix_neutralized(self):
        assert _neutralize_formula("=SUM(A1:A2)") == "'=SUM(A1:A2)"

    def test_plus_prefix_neutralized(self):
        assert _neutralize_formula("+cmd|...") == "'+cmd|..."

    def test_minus_prefix_neutralized(self):
        assert _neutralize_formula("-2+5") == "'-2+5"

    def test_at_prefix_neutralized(self):
        assert _neutralize_formula("@SUM(A1)") == "'@SUM(A1)"

    def test_tab_prefix_neutralized(self):
        assert _neutralize_formula("\tinjected") == "'\tinjected"

    def test_carriage_return_prefix_neutralized(self):
        assert _neutralize_formula("\rhide") == "'\rhide"

    def test_benign_string_unchanged(self):
        assert _neutralize_formula("Mur ext IfcWall") == "Mur ext IfcWall"

    def test_empty_string_unchanged(self):
        assert _neutralize_formula("") == ""

    def test_non_string_passed_through(self):
        # Les ints / floats / bools sont écrits comme types Excel natifs
        assert _neutralize_formula(42) == 42
        assert _neutralize_formula(3.14) == 3.14
        assert _neutralize_formula(True) is True
        assert _neutralize_formula(None) is None


class TestFmtCellNeutralizes:
    """``_fmt_cell`` doit aussi neutraliser puisqu'il est utilisé pour
    formatter les valeurs IFC / DOE / findings avant écriture."""

    def test_str_value_with_formula_prefix(self):
        assert _fmt_cell("=DANGEREUX") == "'=DANGEREUX"

    def test_list_value_with_formula_prefix_after_join(self):
        # La jointure des éléments peut commencer par "=" si le 1er élément
        # commence par "=" (rare mais possible avec des données hostiles).
        assert _fmt_cell(["=evil", "ok"]).startswith("'")

    def test_dict_value_with_formula_prefix_after_serialize(self):
        # Si la 1ère clé commence par "=", la serialisation aussi.
        out = _fmt_cell({"=k": "v"})
        assert out.startswith("'=") or not out.startswith("=")

    def test_none_stays_empty(self):
        assert _fmt_cell(None) == ""


class TestWorkbookOptIn:
    """Vérifie que ``write_xlsx_annex`` ouvre le workbook avec
    ``strings_to_formulas=False`` — ceinture *et* bretelles avec la
    neutralisation par apostrophe."""

    def test_workbook_option_set(self, tmp_path, monkeypatch):
        """Smoke : génère un xlsx réel et vérifie qu'une chaîne ``=`` est
        écrite comme string, pas comme formule."""
        from unittest.mock import MagicMock

        import openpyxl

        from audit_bim.audit.engine import AuditResult
        from audit_bim.audit.findings import ErrorType, Finding, Severity, Theme
        from audit_bim.extraction.model_data import ModelSnapshot
        from audit_bim.reporting.xlsx_annex import write_xlsx_annex
        from audit_bim.requirements.models import BIMPhase

        monkeypatch.setenv("AUDIT_OUTPUT_DIR", str(tmp_path))

        snap = ModelSnapshot()
        snap.project = {"name": "=EVIL_PROJECT"}
        snap.model = {"name": "=EVIL_MODEL"}

        catalog = MagicMock()
        catalog.cch_version = "V3.6"
        catalog.data_spec_source = "spec.xlsx"
        catalog.storey_names = []
        catalog.zone_specs = []
        catalog.room_specs = []

        findings = [
            Finding(
                element_uuid="uuid1",
                ifc_type="IfcWall",
                name="=PAYLOAD",
                theme=Theme.CLASSIFICATION,
                error_type=ErrorType.CLASSIFICATION_MISSING,
                severity=Severity.MEDIUM,
                expected="UniFormat code",
                actual=None,
                ref_cch="=HYPERLINK(evil)",
                recommended_action="-2+5",
            )
        ]
        result = AuditResult(snapshot=snap, catalog=catalog, phase=BIMPhase.PRO, findings=findings)

        out_path = tmp_path / "annex.xlsx"
        write_xlsx_annex(result, out_path)
        assert out_path.exists()

        # Relit le fichier et vérifie que les cellules dangereuses sont
        # préfixées par une apostrophe (ou tout simplement neutralisées).
        wb = openpyxl.load_workbook(out_path, read_only=True)
        ws = wb["Findings (tous)"]
        # Cherche le nom "PAYLOAD" — il doit apparaître mais préfixé.
        found_neutralized = False
        for row in ws.iter_rows(values_only=True):
            for cell in row:
                if isinstance(cell, str) and "PAYLOAD" in cell:
                    assert cell.startswith("'="), f"Cellule non-neutralisée : {cell!r}"
                    found_neutralized = True
        wb.close()
        assert found_neutralized, "Le finding 'PAYLOAD' n'a pas été trouvé dans l'XLSX"
