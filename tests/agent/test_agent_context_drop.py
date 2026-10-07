import json

import pytest
from agent_support import (
    EMAIL,
    SECRET,
    Rig,
    demo_order,
    internal_of,
    public_of,
    rig_with_orders,
    tool_call,
)

from gisting.agent.context import without_earlier_orders
from gisting.agent.policy import load_agent_policy
from gisting.prompt.messages import AssistantMessage, Message, ToolCall, ToolMessage, UserMessage
from gisting.prompt.phrases import load_phrases
from gisting.shopify.demo_email import demo_email
from gisting.tools.policy import load_policy

POLICY = load_agent_policy()
LOOKUP = load_policy()
PLACEHOLDER = POLICY.dropped_placeholder
EMAIL_B = demo_email(SECRET, "#1043")
EMAIL_C = demo_email(SECRET, "#1044")
ASK_A = f"Where is order #1042? My email is {EMAIL}"
ASK_B = f"And order #1043? My email is {EMAIL_B}"
REPLY_A = (
    "Your order is on its way. It is with Test Parcel, tracking number TP-1042. "
    "Expected delivery: October 5."
)
REPLY_B = REPLY_A.replace("1042", "1043")
NO_MATCH = load_phrases().failure_replies["no_match"]
FOUND_TOOL = json.dumps({"status": "found", "order": {"order_number": {"value": "#1042"}}})


def cleaned(history: list[Message]) -> list[Message]:
    return without_earlier_orders(POLICY, LOOKUP, history).messages


def test_a_new_order_number_replaces_the_earlier_order_text_with_the_placeholder() -> None:
    history: list[Message] = [UserMessage(ASK_A), AssistantMessage(REPLY_A), UserMessage(ASK_B)]
    result = without_earlier_orders(POLICY, LOOKUP, history)
    assert result.messages == [
        UserMessage(PLACEHOLDER),
        AssistantMessage(PLACEHOLDER),
        UserMessage(ASK_B),
    ]
    assert (result.removed, result.segments) == (2, 1)


@pytest.mark.parametrize("again", ["1042", "#1042", "order #01042", "is #1042 late?"])
def test_the_same_order_in_any_spelling_keeps_the_history(again: str) -> None:
    history: list[Message] = [UserMessage(ASK_A), AssistantMessage(REPLY_A), UserMessage(again)]
    result = without_earlier_orders(POLICY, LOOKUP, history)
    assert result.messages == history
    assert (result.removed, result.segments) == (0, 0)


def test_a_new_email_for_the_same_order_after_a_shown_reply_drops_the_earlier_text() -> None:
    history: list[Message] = [
        UserMessage(ASK_A),
        AssistantMessage(REPLY_A),
        UserMessage("use x@example.com"),
    ]
    assert cleaned(history) == [
        UserMessage(PLACEHOLDER),
        AssistantMessage(PLACEHOLDER),
        history[-1],
    ]


def test_a_corrected_email_after_a_failed_lookup_keeps_the_order_number_in_context() -> None:
    history: list[Message] = [
        UserMessage("hi"),
        AssistantMessage("Hello! How can I help with your order?"),
        UserMessage("Order #1042, wrong@example.com"),
        AssistantMessage(NO_MATCH),
        UserMessage(f"Sorry, my email is {EMAIL}"),
    ]
    assert cleaned(history) == history


def test_a_failed_first_order_does_not_hide_the_customers_own_text_when_they_try_another() -> None:
    history: list[Message] = [UserMessage(ASK_A), AssistantMessage(NO_MATCH), UserMessage(ASK_B)]
    assert cleaned(history) == history


def test_a_hash_number_outside_the_order_range_is_still_a_switch() -> None:
    history: list[Message] = [UserMessage(ASK_A), AssistantMessage(REPLY_A), UserMessage("#9999?")]
    assert cleaned(history) == [
        UserMessage(PLACEHOLDER),
        AssistantMessage(PLACEHOLDER),
        history[-1],
    ]


def test_a_bare_number_outside_the_order_range_is_not_a_switch() -> None:
    history: list[Message] = [
        UserMessage(ASK_A),
        AssistantMessage(REPLY_A),
        UserMessage("it was 3 weeks ago"),
    ]
    assert cleaned(history) == history


def test_an_email_typed_earlier_still_arms_a_later_order_so_its_reply_is_dropped_on_a_switch() -> (
    None
):
    history: list[Message] = [
        UserMessage(f"Where is order #9999? My email is {EMAIL_B}"),
        AssistantMessage(NO_MATCH),
        UserMessage("order #1043 then"),
        AssistantMessage(REPLY_B),
        UserMessage(ASK_A),
    ]
    assert cleaned(history) == [
        history[0],
        history[1],
        UserMessage(PLACEHOLDER),
        AssistantMessage(PLACEHOLDER),
        history[4],
    ]


def test_a_question_without_identifiers_keeps_the_history() -> None:
    history: list[Message] = [
        UserMessage(ASK_A),
        AssistantMessage(REPLY_A),
        UserMessage("thanks, where is it?"),
    ]
    assert cleaned(history) == history


def test_every_earlier_order_goes_when_the_customer_moves_on_twice() -> None:
    history: list[Message] = [
        UserMessage(ASK_A),
        AssistantMessage(REPLY_A),
        UserMessage(ASK_B),
        AssistantMessage(REPLY_B),
        UserMessage(f"#1044 and {EMAIL_C}"),
    ]
    result = without_earlier_orders(POLICY, LOOKUP, history)
    assert result.messages[:-1] == [UserMessage(PLACEHOLDER), AssistantMessage(PLACEHOLDER)] * 2
    assert (result.removed, result.segments) == (4, 2)


def test_the_current_order_keeps_its_history_after_a_switch() -> None:
    history: list[Message] = [
        UserMessage(ASK_A),
        AssistantMessage(REPLY_A),
        UserMessage(ASK_B),
        AssistantMessage(REPLY_B),
        UserMessage("thanks"),
    ]
    assert cleaned(history)[2:] == history[2:]


def test_tool_traffic_of_the_earlier_order_is_removed_not_masked() -> None:
    call = ToolCall("lookup_order", {"order_number": "#1042", "email": EMAIL})
    history: list[Message] = [
        UserMessage(ASK_A),
        AssistantMessage("", (call,)),
        ToolMessage(FOUND_TOOL),
        AssistantMessage(REPLY_A),
        UserMessage(ASK_B),
    ]
    assert cleaned(history) == [
        UserMessage(PLACEHOLDER),
        AssistantMessage(PLACEHOLDER),
        UserMessage(ASK_B),
    ]


def test_nothing_to_drop_returns_the_messages_unchanged() -> None:
    history: list[Message] = [UserMessage("hi")]
    result = without_earlier_orders(POLICY, LOOKUP, history)
    assert result.messages == history
    assert (result.removed, result.segments) == (0, 0)


def switch_rig(*outputs: str) -> Rig:
    return rig_with_orders([demo_order(1042), demo_order(1043)], *outputs)


HISTORY_AB: list[Message] = [UserMessage(ASK_A), AssistantMessage(REPLY_A), UserMessage(ASK_B)]


def test_the_model_never_sees_the_earlier_order_when_asked_about_another() -> None:
    subject = switch_rig(tool_call(order_number="#1043", email=EMAIL_B))
    result = subject.run(HISTORY_AB)
    prompt = subject.prompt_text(0).rsplit("</tools>", 1)[1]
    for secret in (EMAIL, "TP-1042", "#1042", "GLR-00000412"):
        assert secret not in prompt
    assert PLACEHOLDER in prompt
    assert result.answer == REPLY_B


def test_the_new_order_goes_through_a_fresh_verified_lookup() -> None:
    subject = switch_rig(tool_call(order_number="#1043", email=EMAIL_B))
    subject.run(HISTORY_AB)
    assert subject.tool.calls == [({"order_number": "#1043", "email": EMAIL_B}, "session-9")]


def test_the_old_order_cannot_be_looked_up_again_from_a_message_that_was_dropped() -> None:
    subject = switch_rig(tool_call(order_number="#1042", email=EMAIL), "x")
    history: list[Message] = [
        UserMessage(ASK_A),
        AssistantMessage(REPLY_A),
        UserMessage("what about #1043?"),
    ]
    result = subject.run(history)
    assert subject.tool.calls == []
    assert result.answer == POLICY.needs_input_replies["both"]


def test_the_old_email_does_not_open_the_new_order() -> None:
    subject = switch_rig(tool_call(order_number="#1043", email=EMAIL), "x")
    history: list[Message] = [
        UserMessage(ASK_A),
        AssistantMessage(REPLY_A),
        UserMessage("And order #1043?"),
    ]
    result = subject.run(history)
    assert subject.tool.calls == []
    assert "1042" not in result.answer


def test_an_answer_about_the_new_order_without_a_lookup_never_reaches_the_customer() -> None:
    subject = switch_rig("Your order #1043 has shipped with Test Parcel.")
    history: list[Message] = [
        UserMessage(ASK_A),
        AssistantMessage(REPLY_A),
        UserMessage("And order #1043?"),
    ]
    result = subject.run(history)
    assert "Test Parcel" not in result.answer
    assert subject.tool.calls == []


def test_the_internal_trace_alone_names_the_dropped_context_without_content() -> None:
    subject = switch_rig(tool_call(order_number="#1043", email=EMAIL_B))
    result = subject.run(HISTORY_AB)
    assert internal_of(result)["context_dropped"] == {"messages": 2, "segments": 1}
    assert "context_dropped" not in public_of(result)
    quiet = switch_rig(tool_call(order_number="#1043", email=EMAIL_B)).run(HISTORY_AB[2:])
    assert internal_of(quiet)["context_dropped"] == {"messages": 0, "segments": 0}
    assert "context_dropped" not in public_of(quiet)
