from typing import Any, get_args

import pytest
from agent_support import good_call, public_of, rig, tool_call

from gisting.agent.public_trace import MAX_KNOWLEDGE, PublicOutcomeName, PublicTrace
from gisting.eval.dataclass_json import DecodeError, decode_as
from gisting.kb.entries import MAX_ID_LENGTH
from gisting.tools.trace import PublicOutcome


def test_the_outcome_names_match_the_tool_trace_outcomes() -> None:
    assert set(get_args(PublicOutcomeName)) == {outcome.value for outcome in PublicOutcome}


def test_a_real_public_trace_decodes_into_the_contract() -> None:
    trace = decode_as(PublicTrace, public_of(rig(good_call()).run()))
    assert [call.tool for call in trace.tools] == ["lookup_order"]
    assert trace.tokens.total == trace.tokens.rules + trace.tokens.tools + trace.tokens.history


def test_a_trace_without_tool_calls_decodes_into_the_contract() -> None:
    trace = decode_as(PublicTrace, public_of(rig("Hello there").run()))
    assert trace.tools == ()


def test_a_trace_with_a_refused_call_decodes_into_the_contract() -> None:
    trace = decode_as(PublicTrace, public_of(rig(tool_call(order_number="#9999"), "Sorry").run()))
    assert all(call.outcome in get_args(PublicOutcomeName) for call in trace.tools)


@pytest.mark.parametrize("extra", ["internal", "backend_id", "fallback_reason"])
def test_an_internal_field_in_the_public_trace_breaks_the_contract(extra: str) -> None:
    document: dict[str, Any] = {**public_of(rig(good_call()).run()), extra: "x"}
    with pytest.raises(DecodeError):
        decode_as(PublicTrace, document)


def knowledge_document(*ids: str) -> dict[str, Any]:
    entries = [{"id": identifier, "method": "bm25"} for identifier in ids]
    return {**public_of(rig("Hello there").run()), "knowledge": entries}


def test_the_knowledge_list_may_hold_up_to_the_cap_and_ids_up_to_the_length_limit() -> None:
    longest = "kb-" + "a" * (MAX_ID_LENGTH - 3)
    ids = [longest, "kb-b-1", "kb-c"]
    assert len(decode_as(PublicTrace, knowledge_document(*ids)).knowledge) == MAX_KNOWLEDGE
    assert decode_as(PublicTrace, knowledge_document()).knowledge == ()


@pytest.mark.parametrize(
    "ids",
    [
        ["kb-a", "kb-b", "kb-c", "kb-d"],
        ["kb-" + "a" * (MAX_ID_LENGTH - 2)],
        ["policy"],
        ["kb-"],
        ["kb--a"],
        ["KB-a"],
        ["kb-a b"],
        ["x kb-a"],
        [""],
    ],
)
def test_a_knowledge_list_or_id_beyond_the_contract_marks_is_rejected(ids: list[str]) -> None:
    with pytest.raises(DecodeError):
        decode_as(PublicTrace, knowledge_document(*ids))
