import json
from typing import Any

import pytest
from eval_support import build_case, grader, tool_content

from gisting.eval.case import Case
from gisting.eval.source import Source, build_source
from gisting.prompt.messages import Message, ToolMessage, UserMessage

FOUND_SPEC = {"found": "IN_TRANSIT"}
HIT = {
    "id": "KB1",
    "category": "returns",
    "title": "Return window",
    "answer": "Items can be returned within 14 days. Refunds are issued in 5 days. USA only.",
}
POLICY_FOUND = {"status": "policy_found", "hits": [HIT]}
POLICY_NO_MATCH = {"status": "policy_no_match"}
POLICY_UNAVAILABLE = {"status": "policy_unavailable"}


def second_turn(*policy: dict[str, Any]) -> Source:
    entry = {"category": "found", "kind": "second", "scenario": "IN_TRANSIT", "result": FOUND_SPEC}
    return build_source(build_case({**entry, "policy": list(policy)}), grader())


def source_of(*messages: Message, scenario: str = "IN_TRANSIT") -> Source:
    case = Case("found", "second", scenario, None, None, (UserMessage("x"), *messages))
    return build_source(case, grader())


def tool(document: dict[str, Any]) -> ToolMessage:
    return ToolMessage(json.dumps(document))


def test_the_policy_statuses_come_from_the_grader_data_file() -> None:
    assert grader().policy_statuses == {"policy_found", "policy_no_match", "policy_unavailable"}


@pytest.mark.parametrize("policy", [POLICY_FOUND, POLICY_NO_MATCH, POLICY_UNAVAILABLE])
def test_a_policy_result_after_the_lookup_keeps_the_order_facts(policy: dict[str, Any]) -> None:
    source = second_turn(policy)
    assert source.status == "found"
    assert source.found is not None
    assert source.found.shipments == 1
    assert "TP-5257262993" in source.text


def test_without_a_policy_result_the_order_facts_are_the_same() -> None:
    source = second_turn()
    assert source.status == "found"
    assert source.found is not None


def test_policy_text_still_counts_as_a_legitimate_source() -> None:
    source = second_turn(POLICY_FOUND)
    assert {14, 5} <= source.ints
    assert "returned within 14 days" in source.text


def test_order_enum_values_are_enum_sources_next_to_a_policy_result() -> None:
    assert "IN_TRANSIT" in second_turn(POLICY_FOUND).enums


def test_a_policy_result_alone_has_no_order_status_and_no_found_facts() -> None:
    source = source_of(tool(POLICY_FOUND))
    assert (source.status, source.found, source.missing, source.reference) == (None, None, (), None)


def test_a_status_outside_the_listed_policy_values_is_not_skipped() -> None:
    other = tool({"status": "policy_other", "hits": []})
    source = source_of(ToolMessage(tool_content(FOUND_SPEC)), other)
    assert source.status == "policy_other"
    assert source.found is None


def test_a_missing_list_before_a_policy_result_survives() -> None:
    asked = ToolMessage(tool_content({"missing": ["email"]}))
    source = source_of(asked, tool(POLICY_FOUND), scenario="needs_customer_input")
    assert (source.status, source.missing) == ("needs_customer_input", ("email",))


def lookup(**overrides: str) -> ToolMessage:
    return ToolMessage(tool_content({"found": "IN_TRANSIT", **overrides}))


def turns(*messages: Message) -> Source:
    case = Case("found", "second", "IN_TRANSIT", None, None, messages)
    return build_source(case, grader())


def test_policy_text_from_an_earlier_turn_is_not_a_source() -> None:
    source = turns(UserMessage("a"), tool(POLICY_FOUND), UserMessage("b"), lookup())
    assert not {14, 5} & source.ints
    assert "returned within 14 days" not in source.text


def test_policy_text_of_the_current_turn_is_a_source() -> None:
    source = turns(UserMessage("a"), lookup(), UserMessage("b"), tool(POLICY_FOUND))
    assert {14, 5} <= source.ints
    assert "returned within 14 days" in source.text


def test_policy_text_before_the_lookup_in_the_same_turn_is_a_source() -> None:
    source = turns(UserMessage("a"), tool(POLICY_FOUND), lookup())
    assert {14, 5} <= source.ints


def test_without_any_user_message_every_policy_result_is_current() -> None:
    assert "returned within 14 days" in turns(tool(POLICY_FOUND), lookup()).text


def test_order_results_of_earlier_turns_still_count_and_the_last_lookup_decides_status() -> None:
    source = turns(
        UserMessage("a"),
        lookup(tracking_number="TP-1111111111"),
        UserMessage("b"),
        ToolMessage(tool_content("locked")),
    )
    assert "TP-1111111111" in source.text
    assert source.status == "locked"
