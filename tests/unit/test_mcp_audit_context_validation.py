"""Tests de la validation de contexte avant audit/rapport.

Couvre :
- ``full_audit`` refuse si l'une des 3 infos obligatoires manque
  (adresse, phase, auditeur).
- ``generate_word_report`` refuse de même.
- Les deux tools acceptent ``confirm_context=True`` pour passer
  outre la validation.
- Les inputs utilisateur écrasent les valeurs déduites du snapshot
  et sont marqués ``source="user"``.
- Le rapport Word généré affiche les valeurs utilisateur **sans** la
  mention « déduit — à confirmer », et **avec** cette mention pour les
  valeurs extraites du snapshot.
"""

from __future__ import annotations

import pytest
from docx import Document

from audit_bim.audit.engine import AuditResult
from audit_bim.audit.findings import ErrorType, Finding, Severity, Theme
from audit_bim.extraction.model_data import ModelSnapshot
from audit_bim.mcp import server as mcp_server
from audit_bim.mcp.session import _Session, current_session
from audit_bim.reporting.context import (
    merge_user_context,
)
from audit_bim.requirements.models import BIMPhase, RequirementsCatalog

# ── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIT_OUTPUT_DIR", str(tmp_path))
    sess = _Session()
    token = current_session.set(sess)
    try:
        yield sess, tmp_path
    finally:
        current_session.reset(token)


def _minimal_catalog() -> RequirementsCatalog:
    return RequirementsCatalog(
        cch_version="3.6",
        cch_source_pdf="/tmp/cch.pdf",
        data_spec_source="/tmp/data.xlsx",
        naming_spec_source="/tmp/naming.xlsx",
        properties=[],
        naming_rules=[],
        storey_names=[],
        zone_specs=[],
        room_specs=[],
    )


def _wire_audit(sess) -> None:
    """Pose un AuditResult minimal pour permettre generate_word_report."""
    snap = ModelSnapshot(
        project={"name": "Programme Test"},
        model={"name": "TEST.ifc"},
        sites=[
            {
                "uuid": "S1",
                "name": "Site Liffré",
                "long_name": "12 rue de la Paix, 35340 LIFFRÉ",
                "type": "IfcSite",
            }
        ],
        buildings=[{"uuid": "B1", "name": "Bât A", "type": "IfcBuilding"}],
        storeys=[],
        spaces=[],
        zones=[],
        elements=[],
    ).index()
    sess.result = AuditResult(
        phase=BIMPhase.PRO,
        catalog=_minimal_catalog(),
        snapshot=snap,
        findings=[
            Finding(
                theme=Theme.NAMING_SPACE,
                severity=Severity.MEDIUM,
                error_type=ErrorType.NAMING_MISSING,
                element_uuid="X1",
                ifc_type="IfcSpace",
            )
        ],
    )
    sess.snapshot = snap


def _doc_text(path) -> str:
    doc = Document(str(path))
    parts = [p.text for p in doc.paragraphs]
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                parts.append(cell.text)
    return "\n".join(parts)


# ── generate_word_report : validation ────────────────────────────────────


class TestGenerateWordReportValidation:
    def test_refuses_when_address_missing(self, _isolated):
        sess, _ = _isolated
        _wire_audit(sess)
        res = mcp_server.generate_word_report(
            project_phase="PRO",
            auditor_name="Stanislas",
            # project_address manquant
        )
        assert res.get("status") == "needs_context"
        assert "project_address" in res["missing"]
        assert any(q["key"] == "project_address" for q in res["questions"])

    def test_refuses_when_phase_missing(self, _isolated):
        sess, _ = _isolated
        _wire_audit(sess)
        res = mcp_server.generate_word_report(
            project_address="12 rue de la Paix",
            auditor_name="Stanislas",
            # project_phase manquant
        )
        assert res.get("status") == "needs_context"
        assert "project_phase" in res["missing"]

    def test_refuses_when_auditor_missing(self, _isolated):
        sess, _ = _isolated
        _wire_audit(sess)
        res = mcp_server.generate_word_report(
            project_address="12 rue de la Paix",
            project_phase="PRO",
            # auditor_name manquant
        )
        assert res.get("status") == "needs_context"
        assert "auditor_name" in res["missing"]

    def test_refuses_when_phase_invalid(self, _isolated):
        sess, _ = _isolated
        _wire_audit(sess)
        res = mcp_server.generate_word_report(
            project_address="12 rue de la Paix",
            project_phase="NOPE",  # phase invalide
            auditor_name="Stanislas",
        )
        assert res.get("status") == "needs_context"
        assert "project_phase" in res["missing"]

    def test_accepts_when_all_three_fields_provided(self, _isolated, tmp_path):
        sess, _ = _isolated
        _wire_audit(sess)
        res = mcp_server.generate_word_report(
            output_path="rapport_complet.docx",
            project_address="12 rue de la Paix, 35340 LIFFRÉ",
            project_phase="PRO",
            auditor_name="Stanislas Limouzi",
        )
        # Pas de needs_context — on a un path et size_bytes.
        assert "path" in res
        assert res.get("status") != "needs_context"
        assert (tmp_path / "rapport_complet.docx").exists()

    def test_confirm_context_bypasses_validation(self, _isolated):
        sess, _ = _isolated
        _wire_audit(sess)
        res = mcp_server.generate_word_report(
            output_path="rapport_minimal.docx",
            confirm_context=True,
            # Pas d'address ni phase ni auditor — mais confirm=True passe.
        )
        assert "path" in res
        assert res.get("status") != "needs_context"


# ── full_audit : validation (sans déclencher l'audit complet) ───────────


class TestFullAuditValidation:
    def test_refuses_when_address_missing(self, _isolated):
        sess, _ = _isolated
        # Pas besoin de wire — la validation tombe AVANT toute exécution.
        res = mcp_server.full_audit(
            phase="PRO",
            auditor_name="Stanislas",
            push_mode="none",
        )
        assert res.get("status") == "needs_context"
        assert "project_address" in res["missing"]

    def test_refuses_when_auditor_missing(self, _isolated):
        sess, _ = _isolated
        res = mcp_server.full_audit(
            phase="PRO",
            project_address="12 rue de la Paix",
            push_mode="none",
        )
        assert res.get("status") == "needs_context"
        assert "auditor_name" in res["missing"]

    def test_refuses_when_phase_invalid(self, _isolated):
        sess, _ = _isolated
        res = mcp_server.full_audit(
            phase="WRONG",
            project_address="12 rue de la Paix",
            auditor_name="Stan",
            push_mode="none",
        )
        assert res.get("status") == "needs_context"
        assert "project_phase" in res["missing"]

    def test_validation_fires_before_push_mode_ask(self, _isolated):
        """La validation doit s'exécuter AVANT le check ``push_mode=ask``.
        Sinon, un agent obtiendrait la question push_mode avant de
        savoir qu'il lui manque adresse/auditeur."""
        sess, _ = _isolated
        # push_mode défaut = ask, mais on n'a pas fourni adresse/auditeur
        # → on doit obtenir needs_context, pas needs_user_choice.
        res = mcp_server.full_audit(phase="PRO")
        assert res.get("status") == "needs_context"
        assert res.get("status") != "needs_user_choice"


# ── Rapport Word : marquage source ──────────────────────────────────────


class TestWordReportSourceMarking:
    def test_user_provided_values_have_no_deduced_suffix(self, _isolated, tmp_path):
        sess, _ = _isolated
        _wire_audit(sess)
        mcp_server.generate_word_report(
            output_path="rapport.docx",
            project_address="42 boulevard Saint-Germain, 75005 PARIS",
            project_phase="DCE",
            auditor_name="Stanislas Limouzi",
        )
        text = _doc_text(tmp_path / "rapport.docx")
        # Adresse user-fournie présente, SANS suffixe "à confirmer"
        assert "42 boulevard Saint-Germain" in text
        # Pas de suffixe "déduit — à confirmer" attaché à l'adresse user.
        # On cherche la ligne contenant l'adresse :
        for para_text in text.split("\n"):
            if "42 boulevard Saint-Germain" in para_text:
                assert "déduit" not in para_text, (
                    f"L'adresse user-fournie ne doit pas porter le suffixe « déduit » : "
                    f"{para_text!r}"
                )

    def test_extracted_values_carry_deduced_suffix(self, _isolated, tmp_path):
        """Quand l'adresse est extraite du snapshot (IfcSite.long_name)
        et PAS fournie par l'utilisateur, elle porte le suffixe
        « déduit — à confirmer »."""
        sess, _ = _isolated
        _wire_audit(sess)  # le snapshot contient une adresse via IfcSite
        res = mcp_server.generate_word_report(
            output_path="rapport_extracted.docx",
            # On ne fournit PAS project_address user, mais on bypass
            # la validation pour pouvoir générer le rapport.
            project_phase="PRO",
            auditor_name="Stan",
            confirm_context=True,
        )
        assert "path" in res
        text = _doc_text(tmp_path / "rapport_extracted.docx")
        # L'adresse extraite est présente
        assert "12 rue de la Paix" in text
        # Chercher la ligne adresse et vérifier qu'elle porte le suffixe
        found_line_with_address = False
        for para_text in text.split("\n"):
            if "12 rue de la Paix" in para_text and "Adresse" in para_text:
                found_line_with_address = True
                assert "à confirmer" in para_text, (
                    f"L'adresse extraite doit porter le suffixe « à confirmer » : {para_text!r}"
                )
        assert found_line_with_address, "Ligne « Adresse : ... » non trouvée"

    def test_auditor_name_appears_on_cover_page_and_in_context(self, _isolated, tmp_path):
        sess, _ = _isolated
        _wire_audit(sess)
        mcp_server.generate_word_report(
            output_path="rapport.docx",
            project_address="X",
            project_phase="PRO",
            auditor_name="Jean DUPONT (BET Acme)",
        )
        text = _doc_text(tmp_path / "rapport.docx")
        # Page de garde : ligne « Auteur : ... »
        assert "Auteur : Jean DUPONT (BET Acme)" in text

    def test_phase_user_provided_displayed_correctly(self, _isolated, tmp_path):
        sess, _ = _isolated
        _wire_audit(sess)  # snapshot a phase PRO via _wire_audit
        mcp_server.generate_word_report(
            output_path="rapport.docx",
            project_address="X",
            project_phase="DCE",  # user fournit DCE
            auditor_name="Stan",
        )
        text = _doc_text(tmp_path / "rapport.docx")
        # Phase DCE doit apparaître (user-fournie)
        assert "DCE" in text


# ── Non-régression : sections enrichies toujours présentes ──────────────


class TestEnrichedSectionsStillPresent:
    def test_all_enriched_sections_present_in_validated_report(self, _isolated, tmp_path):
        sess, _ = _isolated
        _wire_audit(sess)
        mcp_server.generate_word_report(
            output_path="rapport.docx",
            project_address="X",
            project_phase="PRO",
            auditor_name="Stan",
        )
        text = _doc_text(tmp_path / "rapport.docx")
        # Sections du modèle de rapport de conformité (structure 0.3)
        for section in (
            "2. Synthèse exécutive",
            "3. Périmètre de l'audit",
            "Maquette auditée",
            "4. Méthodologie",
            "5. Résultats globaux",
            "6. Résultats détaillés",
            "7. Liste des non-conformités",
            "8. Recommandations",
            "9. Conclusion",
            "10. Annexes",
        ):
            assert section in text, f"section manquante dans le rapport : {section!r}"


# ── merge_user_context : tests unitaires de la primitive ────────────────


class TestMergeUserContext:
    def test_overwrites_address_and_marks_source_user(self):
        # Build un contexte minimal avec adresse extraite
        from audit_bim.reporting.context import ReportProjectContext

        base = ReportProjectContext(
            address="Adresse déduite snapshot",
            field_sources={"address": "extracted"},
        )
        new = merge_user_context(base, project_address="Adresse user explicite")
        assert new.address == "Adresse user explicite"
        assert new.source_of("address") == "user"

    def test_no_input_returns_same_instance(self):
        from audit_bim.reporting.context import ReportProjectContext

        base = ReportProjectContext(address="X", field_sources={"address": "extracted"})
        new = merge_user_context(base)
        assert new is base
        # Source inchangée
        assert new.source_of("address") == "extracted"

    def test_empty_string_ignored(self):
        from audit_bim.reporting.context import ReportProjectContext

        base = ReportProjectContext(address="X", field_sources={"address": "extracted"})
        new = merge_user_context(base, project_address="   ")
        # Strings blanches sont ignorées
        assert new is base

    def test_no_hallucination_via_merge(self):
        """``merge_user_context`` ne doit injecter une valeur que si
        l'utilisateur la fournit explicitement. ``None`` n'écrase pas."""
        from audit_bim.reporting.context import ReportProjectContext

        base = ReportProjectContext(
            address="Adresse fiable",
            field_sources={"address": "user"},
        )
        new = merge_user_context(base, project_address=None)
        # Adresse user-fournie inchangée
        assert new.address == "Adresse fiable"
        assert new.source_of("address") == "user"

    def test_missing_information_cleaned_when_field_provided(self):
        """Si missing_information contenait une entrée pour un champ
        que l'utilisateur a comblé, elle doit être retirée."""
        from audit_bim.reporting.context import ReportProjectContext

        base = ReportProjectContext(
            address=None,
            field_sources={"address": "missing"},
            missing_information=[
                "Adresse du projet : non renseignée sur l'IfcSite ni dans les métadonnées BIMData.",
                "Maîtrise d'ouvrage : non identifiée formellement.",
            ],
        )
        new = merge_user_context(base, project_address="Nouvelle adresse")
        assert new.address == "Nouvelle adresse"
        # L'entrée "Adresse du projet" doit avoir disparu
        assert not any("Adresse du projet" in m for m in new.missing_information)
        # Mais l'autre entrée reste
        assert any("Maîtrise d'ouvrage" in m for m in new.missing_information)
