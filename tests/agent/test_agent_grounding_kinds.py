import json
from dataclasses import replace
from pathlib import Path

import pytest
from agent_support import EMAIL

from gisting.agent.guard import UngroundableKind, missing_inputs
from gisting.agent.policy import (
    POLICY_FILE,
    AgentPolicyError,
    Grounding,
    load_agent_policy,
)
from gisting.shopify.jsonvalue import JsonObject

POLICY = load_agent_policy()
TEXTS = [f"Where is #1042? My email is {EMAIL}"]
MIXED = {"lookup_order": {"order_number": Grounding.ORDER_NUMBER, "email": Grounding.QUERY_TERMS}}


def test_the_lookup_arguments_are_grounded_on_the_order_number_and_the_email() -> None:
    assert POLICY.grounded_arguments["lookup_order"] == {
        "order_number": Grounding.ORDER_NUMBER,
        "email": Grounding.EMAIL,
    }


def test_the_reminder_is_grounded_on_the_order_number_only() -> None:
    assert POLICY.grounded_arguments["send_shipping_reminder"] == {
        "order_number": Grounding.ORDER_NUMBER
    }


def test_the_handoff_has_no_input_grounding_and_stays_consent_guarded() -> None:
    assert "handoff_to_human" not in POLICY.grounded_arguments
    assert "handoff_to_human" in POLICY.consent_guards
    assert "handoff_to_human" not in POLICY.consent_exempt


def test_a_lookup_email_mislabelled_as_query_terms_fails_loudly_in_the_guard() -> None:
    mislabelled = replace(POLICY, grounded_arguments={**POLICY.grounded_arguments, **MIXED})
    arguments: JsonObject = {"order_number": "#1042", "email": "someone-else@example.com"}
    with pytest.raises(UngroundableKind):
        missing_inputs(mislabelled, "lookup_order", arguments, TEXTS)


def test_a_lookup_email_mislabelled_as_query_terms_stops_the_policy_from_loading(
    tmp_path: Path,
) -> None:
    document = json.loads(POLICY_FILE.read_text(encoding="utf-8"))
    document["grounded_arguments"]["lookup_order"]["email"] = "query_terms"
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(document))
    with pytest.raises(AgentPolicyError):
        load_agent_policy(path)


def test_a_search_tool_is_left_to_the_search_guard_by_the_input_guard() -> None:
    assert missing_inputs(POLICY, "search_policy", {"query": "refund"}, TEXTS) == []


def test_an_ungrounded_email_is_still_reported_for_the_lookup() -> None:
    arguments: JsonObject = {"order_number": "#1042", "email": "someone-else@example.com"}
    assert missing_inputs(POLICY, "lookup_order", arguments, TEXTS) == ["email"]
