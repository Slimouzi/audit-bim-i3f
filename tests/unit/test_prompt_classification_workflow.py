"""Le prompt AMO doit imposer l'ordre classification **list → accept/reject →
prepare → apply**.

Sans l'étape ``update_suggestion_status(status="accepted")``,
``prepare_classification_update_plan`` (``default_to_accepted_only=True``) ne
retient aucune suggestion → plan vide. Ce test verrouille l'ordre dans le prompt
et interdit la réapparition des tools dépréciés.
"""

from __future__ import annotations

from audit_bim.mcp.prompts import AMO_BIM_I3F_PROMPT

PROMPT = AMO_BIM_I3F_PROMPT


def _first_index(needle: str) -> int:
    idx = PROMPT.find(needle)
    assert idx != -1, f"{needle!r} absent du prompt AMO"
    return idx


def test_classification_workflow_order_list_accept_prepare_apply():
    i_list = _first_index("list_classification_suggestions")
    i_accept = _first_index("update_suggestion_status")
    i_prepare = _first_index("prepare_classification_update_plan")
    i_apply = _first_index("apply_classification_update_plan")
    # Ordre strict : consulter → accepter/rejeter → préparer → appliquer.
    assert i_list < i_accept < i_prepare < i_apply, (
        "Le prompt doit enchaîner list_classification_suggestions → "
        "update_suggestion_status → prepare_classification_update_plan → "
        "apply_classification_update_plan dans cet ordre."
    )


def test_prompt_mentions_accepted_status_requirement():
    # L'acceptation explicite doit être mentionnée (sinon plan vide).
    assert '"accepted"' in PROMPT or "accepted" in PROMPT


def test_prompt_does_not_recommend_deprecated_tools():
    for deprecated in (
        "suggest_classifications",
        "apply_suggested_classifications",
        "doe_enrich_model",
        "create_bcf_topics",
        "create_smart_views",
    ):
        assert deprecated not in PROMPT, f"Le prompt recommande encore {deprecated!r} (déprécié)."
