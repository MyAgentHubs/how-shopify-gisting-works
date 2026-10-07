import pytest
from agent_support import EMAIL, SECRET, demo_order, rig_with_orders, tool_call

from gisting.agent.context import without_earlier_orders
from gisting.agent.policy import load_agent_policy
from gisting.prompt.messages import AssistantMessage, Message, UserMessage
from gisting.shopify.demo_email import demo_email
from gisting.tools.policy import load_policy

POLICY = load_agent_policy()
LOOKUP = load_policy()
PLACEHOLDER = POLICY.dropped_placeholder
EMAIL_B = demo_email(SECRET, "#1043")
REPLY_A = (
    "Your order is on its way. It is with Test Parcel, tracking number TP-1042. "
    "Expected delivery: October 5."
)
BOTH = [
    f"What about #1042 and #1043? My email is {EMAIL}",
    f"What about #1043 and #1042? My email is {EMAIL}",
]


@pytest.mark.parametrize("first", BOTH)
@pytest.mark.parametrize("again", ["#1043", "#1042", "and 1043 again?", "order 1042"])
def test_a_message_naming_two_orders_makes_the_focus_ambiguous_so_any_number_after_it_starts_afresh(
    first: str, again: str
) -> None:
    history: list[Message] = [UserMessage(first), AssistantMessage(REPLY_A), UserMessage(again)]
    result = without_earlier_orders(POLICY, LOOKUP, history)
    assert result.messages == [
        UserMessage(PLACEHOLDER),
        AssistantMessage(PLACEHOLDER),
        history[-1],
    ]
    assert (result.removed, result.segments) == (2, 1)


def test_an_ambiguous_segment_without_a_number_in_the_next_message_is_kept() -> None:
    history: list[Message] = [
        UserMessage(BOTH[0]),
        AssistantMessage(REPLY_A),
        UserMessage("thanks, where is it?"),
    ]
    assert without_earlier_orders(POLICY, LOOKUP, history).messages == history


def test_the_ambiguity_ends_with_the_segment_it_started() -> None:
    history: list[Message] = [
        UserMessage(BOTH[0]),
        AssistantMessage(REPLY_A),
        UserMessage("#1043"),
        AssistantMessage("Which email?"),
        UserMessage("#1043 again"),
    ]
    result = without_earlier_orders(POLICY, LOOKUP, history)
    assert result.messages[2:] == history[2:]


def test_the_model_input_after_a_two_order_message_has_no_facts_of_the_first_order() -> None:
    history: list[Message] = [
        UserMessage(BOTH[0]),
        AssistantMessage(REPLY_A),
        UserMessage("and #1043 again?"),
    ]
    subject = rig_with_orders(
        [demo_order(1042), demo_order(1043)], tool_call(order_number="#1043", email=EMAIL_B)
    )
    subject.run(history)
    prompt = subject.prompt_text(0).rsplit("</tools>", 1)[1]
    for secret in (EMAIL, "TP-1042", "GLR-00000412"):
        assert secret not in prompt
    assert PLACEHOLDER in prompt
