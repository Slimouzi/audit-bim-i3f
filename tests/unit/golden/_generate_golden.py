"""Génère les payloads GOLDEN depuis le code **pré-shim** (commit af230e6).

À exécuter avec ``PYTHONPATH=<worktree af230e6>`` pour que ``audit_bim`` provienne
de l'implémentation historique (builders lisant ``reporting.theming``, prenant un
``AuditResult``). Les JSON produits servent de référence de parité pour
``bim-publication`` (comparaison intégrale côté master).

**Attention — une valeur ne doit PAS être reprise telle quelle.** Depuis le lot
B3, ``originating_system`` vaut ``audit-bim-mcp`` dans les golden BCF, alors
que le code d'af230e6 écrit encore ``audit-bim-i3f``. Régénérer sans
réappliquer la provenance courante annulerait B3 sur 28 lignes — et la
seule chose qui le signalerait serait l'échec de
``test_output_provenance.py::test_active_output_provenance_no_longer_mentions_old_distribution``.

Usage :
    PYTHONPATH=<wt> AUDIT_OUTPUT_DIR=/tmp .venv/bin/python \
        tests/unit/golden/_generate_golden.py <dest_dir>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import audit_bim  # noqa: F401 — doit venir du worktree af230e6
from audit_bim.actions import prepare_bcf, prepare_smart_view_from_filter, prepare_smart_views
from audit_bim.audit.engine import AuditResult
from audit_bim.audit.findings import ErrorType, Finding, Severity, Theme
from audit_bim.bcf.builder import build_bcf_payloads
from audit_bim.extraction.model_data import ModelSnapshot
from audit_bim.requirements.models import BIMPhase
from audit_bim.smartview.builder import build_smartview_payload_from_uuids, build_smartview_payloads

PREFIX = "I3F Audit — "
MODEL_ID = 1674450
TARGET = {"cloud_id": "33617", "project_id": "2698917", "model_id": "1674450"}


def _snapshot() -> ModelSnapshot:
    return ModelSnapshot(
        project={"name": "I3F"},
        model={"name": "DIEPPE.ifc"},
        elements=[
            {"uuid": "W1", "type": "IfcWallStandardCase", "name": "Mur porteur"},
            {"uuid": "D1", "type": "IfcDoor", "object_type": "Porte EI30"},
        ],
    ).index()


def _findings() -> list[Finding]:
    return [
        Finding(
            theme=Theme.CLASSIFICATION,
            severity=Severity.MEDIUM,
            error_type=ErrorType.CLASSIFICATION_MISSING,
            element_uuid="W1",
            ifc_type="IfcWallStandardCase",
            name="Mur",
            ref_cch="CCH-CLS-1",
        ),
        Finding(
            theme=Theme.PROPERTY_MISSING,
            severity=Severity.HIGH,
            error_type=ErrorType.PROPERTY_MISSING,
            element_uuid="W1",
            ifc_type="IfcWallStandardCase",
            name="Mur",
        ),
        Finding(
            theme=Theme.PROPERTY_MISSING,
            severity=Severity.LOW,
            error_type=ErrorType.PROPERTY_MISSING,
            element_uuid="D1",
            ifc_type="IfcDoor",
            name="Porte",
        ),
    ]


def _plan_dump(plan) -> dict:
    """Partie déterministe d'un WritePlan (hors plan_id/created_at volatiles)."""
    return {
        "kind": plan.kind.value,
        "target": plan.target,
        "summary": plan.summary,
        "items": plan.items,
        "risks": plan.risks,
    }


def main(dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    res = AuditResult(phase=BIMPhase.AVP, catalog=None, snapshot=_snapshot(), findings=_findings())

    golden = {
        "bcf_payloads.json": build_bcf_payloads(res, prefix=PREFIX, model_id=MODEL_ID),
        "smartview_payloads.json": build_smartview_payloads(res, prefix=PREFIX, model_id=MODEL_ID),
        "smartview_from_uuids.json": build_smartview_payload_from_uuids(
            ["W1", "W1", "D1"],
            title="Sélection",
            color="#123456",
            model_id=MODEL_ID,
            element_by_uuid=res.snapshot.element_by_uuid,
        ),
        "prepare_bcf.json": _plan_dump(prepare_bcf(res, target=TARGET)),
        "prepare_smart_views.json": _plan_dump(prepare_smart_views(res, target=TARGET)),
        "prepare_smart_view_from_filter.json": _plan_dump(
            prepare_smart_view_from_filter(
                ["W1", "D1"], name="Sélection", target=TARGET, description="note"
            )
        ),
    }
    for fname, data in golden.items():
        (dest / fname).write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True))
        print("wrote", fname)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
