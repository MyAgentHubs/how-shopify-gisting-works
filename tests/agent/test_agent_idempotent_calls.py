from agent_support import Rig, internal_of, public_of, rig
from test_agent_handoff import CONFIRMED, SESSION, handoff_call

from gisting.agent.state import TurnState
from gisting.agent.turn import execute
from gisting.prompt.messages import Message, ToolMessage, UserMessage
from gisting.prompt.parse import CallRequest, ParsedOutput

HUMAN: list[Message] = [UserMessage("I want to talk to a human")]


def parsed_of(*calls: tuple[str, dict[str, str]]) -> ParsedOutput:
    return ParsedOutput("", tuple(CallRequest(name, arguments, None) for name, arguments in calls))


def test_two_identical_handoffs_in_one_output_open_one_ticket_and_confirm_once() -> None:
    subject = rig(handoff_call() * 2, "never used")
    result = subject.run(HUMAN)
    assert subject.handoff.calls == [({"reason": "customer_request"}, SESSION)]
    assert result.answer == CONFIRMED
    assert subject.model.outputs == ["never used"]


def test_the_second_identical_call_reuses_the_result_of_the_first() -> None:
    subject = rig(handoff_call() * 2, "never used")
    result = subject.run(HUMAN)
    calls = internal_of(result)["tool_calls"]
    assert [call["name"] for call in calls] == ["handoff_to_human", "handoff_to_human"]
    assert calls[0]["trace"]["result_type"] == "HandedOff"
    assert calls[1]["trace"] == {"reused": True, "result_type": "HandedOff"}
    assert len(public_of(result)["tools"]) == 1


def test_one_call_still_runs_once() -> None:
    subject = rig(handoff_call(), "never used")
    subject.run(HUMAN)
    assert len(subject.handoff.calls) == 1


def state_after(*calls: tuple[str, dict[str, str]]) -> tuple[Rig, TurnState]:
    subject = rig()
    state = TurnState([UserMessage("remind me about #1042 and #1043")])
    execute(subject.deps, state, SESSION, parsed_of(*calls))
    return subject, state


def test_calls_with_different_arguments_each_run() -> None:
    reminders = [
        ("send_shipping_reminder", {"order_number": "#1042"}),
        ("send_shipping_reminder", {"order_number": "#1043"}),
    ]
    subject, state = state_after(*reminders)
    assert len(set(state.batch)) == 2
    assert [m for m in state.messages if isinstance(m, ToolMessage)]
    assert subject.reminder.calls == [
        ({"order_number": "#1042"}, SESSION),
        ({"order_number": "#1043"}, SESSION),
    ]


def test_the_same_call_in_a_later_step_of_the_turn_runs_once() -> None:
    subject = rig()
    state = TurnState([UserMessage("remind me about #1042")])
    call = ("send_shipping_reminder", {"order_number": "#1042"})
    execute(subject.deps, state, SESSION, parsed_of(call))
    execute(subject.deps, state, SESSION, parsed_of(call))
    assert subject.reminder.calls == [({"order_number": "#1042"}, SESSION)]
    results = [m.content for m in state.messages if isinstance(m, ToolMessage)]
    assert len(results) == 2
    assert results[0] == results[1]
