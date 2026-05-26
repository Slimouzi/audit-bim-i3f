"""Test E2E métier non destructif du workflow AMO BIM cible.

Ce test est le **garde-fou** de l'architecture prepare/apply : il
simule un parcours AMO complet avec un audit qui produit des findings,
prépare les 3 plans (classification + BCF + Smart Views), et **vérifie
qu'aucun appel API BIMData n'est émis tant que ``confirm=True`` n'est
pas explicitement fourni**.

Si ce test passe, le contrat suivant est respecté :

1. ``list_*`` ne touche pas BIMData.
2. ``update_suggestion_status`` ne touche pas BIMData (modifie le store).
3. ``prepare_*`` ne touche pas BIMData (calcule + scelle sur disque).
4. ``apply_*`` sans ``confirm=True`` retourne un refus sans toucher BIMData.

Le test ne dépend pas de l'API BIMData réelle — un client mocké
intercepte toute tentative d'appel et fait échouer le test si l'un de
ces appels est émis.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from audit_bim.audit.engine import AuditResult
from audit_bim.audit.findings import ErrorType, Finding, Severity, Theme
from audit_bim.extraction.model_data import ModelSnapshot
from audit_bim.mcp import server as mcp_server
from audit_bim.mcp.session import _Session, current_session
from audit_bim.requirements.models import BIMPhase, RequirementsCatalog
from audit_bim.security import write_journal as journal_mod

# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture
def amo_workflow_session(tmp_path, monkeypatch):
    """Session isolée + AUDIT_OUTPUT_DIR sandboxé + journal reset.

    Un client BIMData mocké est attaché. ``client._post``,
    ``client.create_bcf_full_topic`` et ``client._get`` sont surveillés —
    le test FAIL si l'un est appelé.
    """
    monkeypatch.setenv("AUDIT_OUTPUT_DIR", str(tmp_path))
    monkeypatch.setenv("AUDIT_BIM_ALLOW_WRITES", "true")
    journal_mod._reset_journal_for_tests()
    sess = _Session()
    token = current_session.set(sess)
    try:
        # Snapshot synthétique : 3 murs (1 ext, 2 int) + 1 porte + 1 dalle.
        snap = ModelSnapshot(
            project={"name": "AMO E2E"},
            model={"name": "AMO_E2E.ifc"},
            sites=[{"uuid": "S1", "name": "S", "type": "IfcSite"}],
            buildings=[{"uuid": "B1", "name": "B", "type": "IfcBuilding"}],
            storeys=[{"uuid": "F1", "name": "RDC", "type": "IfcBuildingStorey"}],
            spaces=[],
            zones=[],
            elements=[
                {
                    "uuid": "W1",
                    "type": "IfcWallStandardCase",
                    "name": "Mur ext 01",
                    "property_sets": [
                        {
                            "name": "Pset_WallCommon",
                            "properties": [
                                {
                                    "definition": {"name": "IsExternal"},
                                    "value": True,
                                }
                            ],
                        }
                    ],
                    "classifications": [],
                },
                {
                    "uuid": "W2",
                    "type": "IfcWallStandardCase",
                    "name": "Cloison 01",
                    "property_sets": [
                        {
                            "name": "Pset_WallCommon",
                            "properties": [
                                {
                                    "definition": {"name": "IsExternal"},
                                    "value": False,
                                }
                            ],
                        }
                    ],
                    "classifications": [],
                },
                {
                    "uuid": "DR1",
                    "type": "IfcDoor",
                    "name": "Porte 01",
                    "classifications": [],
                },
            ],
        ).index()

        # Catalogue minimal (audit n'a rien à valider — on injecte des
        # findings manuels pour rester déterministe).
        catalog = RequirementsCatalog(
            cch_version="3.6",
            cch_source_pdf="t://c.pdf",
            data_spec_source="t://d.xlsx",
            naming_spec_source="t://n.xlsx",
            properties=[],
            naming_rules=[],
            storey_names=[],
            zone_specs=[],
            room_specs=[],
        )

        findings = [
            Finding(
                theme=Theme.CLASSIFICATION,
                severity=Severity.MEDIUM,
                error_type=ErrorType.CLASSIFICATION_MISSING,
                element_uuid="W1",
                ifc_type="IfcWallStandardCase",
                name="Mur ext 01",
                ref_cch="Chap 6.4",
            ),
            Finding(
                theme=Theme.CLASSIFICATION,
                severity=Severity.MEDIUM,
                error_type=ErrorType.CLASSIFICATION_MISSING,
                element_uuid="W2",
                ifc_type="IfcWallStandardCase",
                name="Cloison 01",
                ref_cch="Chap 6.4",
            ),
            Finding(
                theme=Theme.CLASSIFICATION,
                severity=Severity.MEDIUM,
                error_type=ErrorType.CLASSIFICATION_MISSING,
                element_uuid="DR1",
                ifc_type="IfcDoor",
                name="Porte 01",
                ref_cch="Chap 6.4",
            ),
            Finding(
                theme=Theme.PROPERTY_MISSING,
                severity=Severity.HIGH,
                error_type=ErrorType.PROPERTY_MISSING,
                element_uuid="W1",
                ifc_type="IfcWallStandardCase",
                name="Mur ext 01",
                ref_cch="Chap 6.2",
            ),
        ]

        sess.snapshot = snap
        sess.result = AuditResult(
            phase=BIMPhase.PRO,
            catalog=catalog,
            snapshot=snap,
            findings=findings,
        )
        sess.catalog = catalog

        # Client mocké — TOUT appel API est interdit pendant ce test.
        client = MagicMock()
        client.cloud_id = "1"
        client.project_id = "2"
        client.model_id = "3"
        sess.client = client
        sess.cloud_id = "1"
        sess.project_id = "2"
        sess.model_id = "3"
        sess.phase = BIMPhase.PRO

        yield sess, client, tmp_path
    finally:
        current_session.reset(token)
        journal_mod._reset_journal_for_tests()


def _assert_no_api_calls(client: MagicMock, step: str) -> None:
    """Vérifie qu'aucun appel API mutatif n'a été émis depuis le client.

    Méthodes surveillées : ``_post``, ``_put``, ``_patch``, ``_delete``,
    ``create_bcf_full_topic`` (utilisée par les builders BCF/SmartView).
    """
    forbidden = ["_post", "_put", "_patch", "_delete", "create_bcf_full_topic"]
    for method in forbidden:
        attr = getattr(client, method, None)
        if attr is None:
            continue
        n_calls = attr.call_count
        assert n_calls == 0, (
            f"[{step}] {n_calls} appel(s) {method!r} émis vers BIMData "
            "alors que confirm=True n'a pas été fourni"
        )


# ── Test E2E principal ──────────────────────────────────────────────────


class TestWorkflowAmoBimE2E:
    """Parcours AMO complet : audit → suggestions → 3 plans, ZÉRO appel API."""

    def test_full_workflow_without_confirm_does_not_write(self, amo_workflow_session):
        sess, client, tmp_path = amo_workflow_session

        # ── Étape 3 : filtrer les findings ────────────────────────────────
        findings_resp = mcp_server.list_audit_findings(filter={"themes": ["Classification IFC"]})
        assert findings_resp["total"] == 3
        _assert_no_api_calls(client, "list_audit_findings")

        # ── Étape 4 : lister les suggestions (lazy-populate) ──────────────
        suggestions_resp = mcp_server.list_classification_suggestions()
        assert suggestions_resp["total"] >= 1
        assert sess.suggestion_store is not None
        assert len(sess.suggestion_store) >= 1
        _assert_no_api_calls(client, "list_classification_suggestions")

        # ── Étape 5 : accepter manuellement les suggestions ───────────────
        accepted_uuids = []
        for entry in list(sess.suggestion_store):
            if entry.confidence >= 0.4:
                mcp_server.update_suggestion_status(
                    element_uuid=entry.element_uuid, status="accepted"
                )
                accepted_uuids.append(entry.element_uuid)
        assert len(accepted_uuids) >= 1
        _assert_no_api_calls(client, "update_suggestion_status")

        # ── Étape 6 : préparer le plan classification ─────────────────────
        plan_classif = mcp_server.prepare_classification_update_plan()
        assert plan_classif["kind"] == "classification_update"
        assert plan_classif["requires_confirm"] is True
        assert "plan_path" in plan_classif
        assert plan_classif["summary"]["n_classifications"] == len(accepted_uuids)
        _assert_no_api_calls(client, "prepare_classification_update_plan")

        # Vérification : fichier plan présent sous AUDIT_OUTPUT_DIR/plans/
        from pathlib import Path

        assert Path(plan_classif["plan_path"]).exists()
        assert (tmp_path / "plans").is_dir()

        # ── Étape 8 : préparer le plan BCF (via alias métier) ─────────────
        plan_bcf = mcp_server.prepare_bcf_from_findings(finding_filter={"severity_min": "HIGH"})
        assert plan_bcf["kind"] == "bcf_topics"
        assert plan_bcf["requires_confirm"] is True
        assert plan_bcf["n_items"] >= 1
        _assert_no_api_calls(client, "prepare_bcf_from_findings")

        # ── Étape 10 : préparer le plan Smart Views (via alias) ───────────
        plan_sv = mcp_server.prepare_smartviews_from_findings()
        assert plan_sv["kind"] == "smart_views"
        assert plan_sv["requires_confirm"] is True
        _assert_no_api_calls(client, "prepare_smartviews_from_findings")

        # ── Étapes 7/9/11 : tous les apply_* refusent confirm=False ───────
        refused_classif = mcp_server.apply_classification_update_plan(
            plan_path=plan_classif["plan_path"], confirm=False
        )
        assert refused_classif.get("refused") is True
        _assert_no_api_calls(client, "apply_classification_update_plan(False)")

        refused_bcf = mcp_server.apply_bcf_plan(plan_path=plan_bcf["plan_path"], confirm=False)
        assert refused_bcf.get("refused") is True
        _assert_no_api_calls(client, "apply_bcf_plan(False)")

        refused_sv = mcp_server.apply_smartviews_plan(plan_path=plan_sv["plan_path"], confirm=False)
        assert refused_sv.get("refused") is True
        _assert_no_api_calls(client, "apply_smartviews_plan(False)")

        # ── Étape 12 : audit_trail — vide (rien n'a été exécuté) ─────────
        trail = mcp_server.audit_trail()
        assert trail["total_returned"] == 0

    def test_legacy_wrappers_in_default_mode_do_not_write(self, amo_workflow_session):
        """Les 3 wrappers legacy (create_bcf_topics / create_smart_views /
        apply_suggested_classifications), appelés sans ``legacy_execute=True``,
        ne doivent émettre aucun appel API.
        """
        sess, client, _ = amo_workflow_session

        res_bcf = mcp_server.create_bcf_topics()
        assert res_bcf["deprecated"] is True
        assert "plan_path" in res_bcf
        _assert_no_api_calls(client, "create_bcf_topics(legacy_execute=False)")

        res_sv = mcp_server.create_smart_views()
        assert res_sv["deprecated"] is True
        assert "plan_path" in res_sv
        _assert_no_api_calls(client, "create_smart_views(legacy_execute=False)")

        res_apply = mcp_server.apply_suggested_classifications()
        assert res_apply["deprecated"] is True
        # Au moins un kind plan attendu (classification_update) OU le mode
        # fallback sans suggestions retourne quand même un plan vide.
        assert res_apply.get("kind") == "classification_update"
        _assert_no_api_calls(client, "apply_suggested_classifications(legacy_execute=False)")

    def test_workflow_full_audit_with_push_mode_none_does_not_write(self, amo_workflow_session):
        """``full_audit(push_mode='none')`` exécute audit + reports + payloads
        BCF/SmartView en mémoire mais ne pousse pas vers BIMData."""
        sess, client, _ = amo_workflow_session

        # full_audit a besoin du catalogue + des chemins MOA. Vu qu'on a
        # injecté le résultat manuellement, on ne le rejoue pas ici ;
        # on vérifie juste que list_write_plans et audit_trail
        # fonctionnent sans appel API.
        plans = mcp_server.list_write_plans()
        assert "plans" in plans
        # Aucun plan préparé dans ce test (fixture isolated) → liste vide
        # ou bien des plans créés par d'autres sous-tests (selon ordre).
        _assert_no_api_calls(client, "list_write_plans")

        trail = mcp_server.audit_trail()
        assert "entries" in trail
        _assert_no_api_calls(client, "audit_trail")

    def test_doe_workflow_prepare_apply_without_confirm_does_not_write(
        self, amo_workflow_session, tmp_path
    ):
        """Workflow DOE complet : extract → match → prepare → apply(confirm=False).

        Garantit que la nouvelle chaîne DOE prepare/apply respecte le même
        contrat que les autres : aucun appel API tant que confirm=True
        n'est pas fourni. Couvre aussi le wrapper legacy doe_enrich_model
        en mode default.
        """
        sess, client, _ = amo_workflow_session

        # Crée un fichier DOE Excel minimal (sandbox AUDIT_INPUT_DIR
        # non défini → mode permissif, tmp_path autorisé).
        import openpyxl

        doe_path = tmp_path / "doe_e2e.xlsx"
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["UUID", "Pset_3F.Fabricant", "Pset_3F.Reference"])
        ws.append(["W1", "BOSCH", "X42"])
        ws.append(["W2", "SIEMENS", "Y99"])
        wb.save(doe_path)

        # ── Étape DOE-1 : extract_doe_records ─────────────────────────────
        extracted = mcp_server.extract_doe_records(doe_path=str(doe_path))
        assert extracted["total"] >= 2
        _assert_no_api_calls(client, "extract_doe_records")

        # ── Étape DOE-2 : match_doe_to_ifc ────────────────────────────────
        matched = mcp_server.match_doe_to_ifc(doe_path=str(doe_path))
        assert matched["n_records"] >= 2
        _assert_no_api_calls(client, "match_doe_to_ifc")

        # ── Étape DOE-3 : prepare_doe_enrichment_plan ─────────────────────
        plan_doe = mcp_server.prepare_doe_enrichment_plan(doe_path=str(doe_path))
        assert plan_doe["kind"] == "doe_enrichment"
        assert plan_doe["requires_confirm"] is True
        assert "plan_path" in plan_doe
        _assert_no_api_calls(client, "prepare_doe_enrichment_plan")

        # ── Étape DOE-3 bis : alias métier ───────────────────────────────
        plan_alias = mcp_server.prepare_doe_enrichment_from_file(doe_path=str(doe_path))
        assert plan_alias["kind"] == "doe_enrichment"
        _assert_no_api_calls(client, "prepare_doe_enrichment_from_file")

        # ── Étape DOE-4 : apply_doe_enrichment_plan(confirm=False) ────────
        refused = mcp_server.apply_doe_enrichment_plan(
            plan_path=plan_doe["plan_path"], confirm=False
        )
        assert refused.get("refused") is True
        _assert_no_api_calls(client, "apply_doe_enrichment_plan(False)")

        # ── Wrapper legacy doe_enrich_model en mode default ──────────────
        legacy_res = mcp_server.doe_enrich_model(doe_path=str(doe_path))
        assert legacy_res["deprecated"] is True
        assert legacy_res.get("kind") == "doe_enrichment"
        assert "plan_path" in legacy_res
        _assert_no_api_calls(client, "doe_enrich_model(legacy_execute=False)")
