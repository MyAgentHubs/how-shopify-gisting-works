import json
from dataclasses import replace

import pytest
from agent_support import EMAIL, RENDERED, SESSION, good_call, internal_of, rig, tool_call

from gisting.agent.policy import FallbackReason, InvalidCode
from gisting.agent.state import TurnState
from gisting.agent.turn import execute
from gisting.prompt.messages import AssistantMessage, ToolCall, UserMessage
from gisting.prompt.parse import CallRequest, ParsedOutput
from gisting.shopify.jsonvalue import JsonObject
from gisting.tools.lookup_order import ToolResponse
from gisting.tools.trace import InternalTrace, PublicOutcome, PublicTrace, Trace

HOSTILE = "Your order will arrive on Tuesday, October 6 with FedEx, tracking number FX-99."
HANDOFF = tool_call("handoff_to_human")
OTHER_ORDER = tool_call(order_number="#1042", email="other@example.com")


def hostile_in(text: str) -> bool:
    return "Tuesday" in text or "FedEx" in text


@pytest.mark.parametrize(
    "output",
    [
        good_call() + "\n" + good_call(),
        good_call() + good_call(),
        f"One moment. {good_call()}{good_call()}",
        good_call() + OTHER_ORDER,
        good_call() + HANDOFF,
        HANDOFF + good_call(),
    ],
    ids=[
        "newline",
        "adjacent",
        "text_around",
        "two_orders",
        "lookup_then_handoff",
        "handoff_first",
    ],
)
def test_a_lookup_that_shares_its_output_with_another_call_is_rejected_unexecuted(
    output: str,
) -> None:
    subject = rig(output, good_call(), max_tool_calls=2)
    result = subject.run()
    assert result.answer == RENDERED
    assert len(subject.tool.calls) == 1
    assert subject.handoff.calls == []
    assert len(subject.model.prompts) == 2
    assert f'"code": "{InvalidCode.ONE_LOOKUP_AT_A_TIME}"' in subject.prompt_text(1)
    problems = [call["problem"] for call in internal_of(result)["tool_calls"]]
    assert problems[-1] is None
    assert all(problems[:-1])


def test_the_code_the_model_is_told_names_one_lookup_at_a_time() -> None:
    assert InvalidCode.ONE_LOOKUP_AT_A_TIME.value == "one_lookup_at_a_time"


def test_a_second_output_with_two_lookups_degrades_to_the_fixed_reply() -> None:
    twice = good_call() + good_call()
    subject = rig(twice, twice, HOSTILE, max_tool_calls=2)
    result = subject.run()
    assert result.fallback_reason is FallbackReason.INVALID_TOOL_CALL
    assert subject.tool.calls == []
    assert not hostile_in(result.answer)


@pytest.mark.parametrize(
    "outputs",
    [
        [good_call() + "\n" + good_call(), HOSTILE],
        [good_call() + HANDOFF, HOSTILE],
        [good_call(), HOSTILE],
        [tool_call(order_number="#1042"), good_call(), HOSTILE],
        [HANDOFF, good_call(), HOSTILE],
    ],
    ids=["two_lookups", "lookup_and_handoff", "plain", "after_invalid", "after_blocked_handoff"],
)
def test_after_a_lookup_result_the_model_text_never_reaches_the_customer(
    outputs: list[str],
) -> None:
    subject = rig(*outputs, max_tool_calls=2)
    result = subject.run()
    assert not hostile_in(result.answer)
    if subject.tool.calls:
        assert result.answer == RENDERED
        assert internal_of(result)["reply_source"] == "code"


class OddTool:
    def call(self, arguments: JsonObject, session_id: str) -> ToolResponse:
        internal = InternalTrace("lookup_order", session_id, "#1042", "odd", None, None, 0)
        public = PublicTrace("lookup_order", "#1042", PublicOutcome.COMPLETED)
        return ToolResponse({"status": "sideways"}, Trace(internal, public))


def test_a_lookup_result_with_a_status_the_renderer_does_not_know_ends_in_the_fallback() -> None:
    subject = rig(good_call(), HOSTILE)
    subject.deps = replace(subject.deps, tools={"lookup_order": OddTool()})
    result = subject.run()
    assert result.fallback_reason is FallbackReason.UNRENDERABLE_ORDER
    assert not hostile_in(result.answer)
    assert len(subject.model.prompts) == 1


def test_text_around_an_executed_call_is_kept_as_assistant_content() -> None:
    subject = rig()
    state = TurnState([UserMessage("hi")])
    parsed = ParsedOutput(
        "One moment.",
        (CallRequest("lookup_order", {"order_number": "#1042", "email": EMAIL}, None),),
    )
    execute(subject.deps, state, SESSION, parsed)
    message = state.messages[1]
    assert isinstance(message, AssistantMessage)
    assert message.content == "One moment."
    assert message.tool_calls == (
        ToolCall("lookup_order", {"order_number": "#1042", "email": EMAIL}),
    )
    assert json.loads(state.messages[2].content)["status"] == "found"
