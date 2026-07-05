"""La CLI ``audit-bim`` **prépare** des plans et n'écrit **jamais** dans BIMData.

Garde-fou de non-régression : on injecte un client dont toute méthode d'écriture
(`create_bcf_full_topic`) **échoue au moindre appel**. Si la CLI tentait une
écriture directe (régression du chemin `push_*`), le test casserait.

Vérifie aussi que la **cible** des plans provient du **client effectif**
(`client.cloud_id/project_id/model_id`), pas des arguments bruts.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from audit_bim import cli


def _fake_snapshot() -> MagicMock:
    snap = MagicMock()
    snap.project = {"name": "Projet"}
    snap.model = {"name": "MODELE.ifc"}
    snap.summary.return_value = {}
    return snap


def _fake_result() -> MagicMock:
    result = MagicMock()
    result.findings = []
    result.summary.return_value = {"n_findings": 0}
    return result


def test_cli_prepares_plans_and_never_writes(tmp_path, monkeypatch):
    # Client dont l'écriture échoue au moindre appel + cible effective distincte
    # des arguments bruts.
    client = MagicMock()
    client.cloud_id = "EFF-CLOUD"
    client.project_id = "EFF-PROJECT"
    client.model_id = "EFF-MODEL"
    client.create_bcf_full_topic.side_effect = AssertionError(
        "La CLI ne doit JAMAIS écrire dans BIMData (create_bcf_full_topic)."
    )

    fake_plan = {"plan_id": "p", "target": {}}

    argv = [
        "audit-bim",
        "--cloud-id",
        "ARG-CLOUD",  # bruts, volontairement != client
        "--project-id",
        "ARG-PROJECT",
        "--model-id",
        "ARG-MODEL",
        "--phase",
        "PRO",
        "--out-dir",
        str(tmp_path),
        "--push",
        "both",
        "--cch-pdf",
        "x",
        "--data-spec",
        "y",
        "--naming-spec",
        "z",
    ]
    monkeypatch.setattr("sys.argv", argv)

    with (
        patch.object(cli, "build_catalog", return_value=MagicMock(summary=lambda: {})),
        patch.object(cli, "BIMDataClient", return_value=client),
        patch.object(cli, "extract_snapshot", return_value=_fake_snapshot()),
        patch.object(cli, "run_audit", return_value=_fake_result()),
        patch.object(cli, "write_xlsx_annex", return_value=tmp_path / "a.xlsx"),
        patch.object(cli, "write_word_report", return_value=tmp_path / "a.docx"),
        patch.object(cli, "prepare_bcf", return_value=fake_plan) as m_bcf,
        patch.object(cli, "prepare_smart_views", return_value=fake_plan) as m_sv,
        patch.object(cli, "save_plan", side_effect=lambda p: tmp_path / "plan.json"),
    ):
        rc = cli.main()

    assert rc == 0
    # Jamais d'écriture BIMData.
    client.create_bcf_full_topic.assert_not_called()
    # Plans préparés pour BCF + Smart Views.
    m_bcf.assert_called_once()
    m_sv.assert_called_once()
    # Cible issue du CLIENT effectif, pas des arguments bruts.
    for m in (m_bcf, m_sv):
        target = m.call_args.kwargs["target"]
        assert target["cloud_id"] == "EFF-CLOUD"
        assert target["project_id"] == "EFF-PROJECT"
        assert target["model_id"] == "EFF-MODEL"
        assert target["model_name"] == "MODELE.ifc"


def test_cli_push_none_prepares_no_plan(tmp_path, monkeypatch):
    client = MagicMock(cloud_id="c", project_id="p", model_id="m")
    client.create_bcf_full_topic.side_effect = AssertionError("no write")

    monkeypatch.setattr(
        "sys.argv",
        [
            "audit-bim",
            "--cloud-id",
            "c",
            "--project-id",
            "p",
            "--model-id",
            "m",
            "--phase",
            "PRO",
            "--out-dir",
            str(tmp_path),
            "--push",
            "none",
            "--cch-pdf",
            "x",
            "--data-spec",
            "y",
            "--naming-spec",
            "z",
        ],
    )
    with (
        patch.object(cli, "build_catalog", return_value=MagicMock(summary=lambda: {})),
        patch.object(cli, "BIMDataClient", return_value=client),
        patch.object(cli, "extract_snapshot", return_value=_fake_snapshot()),
        patch.object(cli, "run_audit", return_value=_fake_result()),
        patch.object(cli, "write_xlsx_annex", return_value=tmp_path / "a.xlsx"),
        patch.object(cli, "write_word_report", return_value=tmp_path / "a.docx"),
        patch.object(cli, "prepare_bcf") as m_bcf,
        patch.object(cli, "prepare_smart_views") as m_sv,
        patch.object(cli, "save_plan", side_effect=lambda p: tmp_path / "plan.json"),
    ):
        rc = cli.main()

    assert rc == 0
    m_bcf.assert_not_called()
    m_sv.assert_not_called()
    client.create_bcf_full_topic.assert_not_called()
