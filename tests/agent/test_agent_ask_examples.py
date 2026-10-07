import pytest
from agent_support import EMAIL, internal_of, rig, tool_call

from gisting.agent.policy import load_agent_policy
from gisting.prompt.messages import Message, UserMessage
from gisting.prompt.phrases import load_phrases
from gisting.shopify.demo_email import EMAIL_DOMAIN
from gisting.tools.policy import load_policy

PHRASES = load_phrases()
POLICY = load_agent_policy()
EXAMPLE_NUMBER = PHRASES.ask_examples["order_number"]
EXAMPLE_EMAIL = PHRASES.ask_examples["email"]
ASKS = POLICY.needs_input_replies
BARE = POLICY.needs_input_bare_replies


def test_the_example_order_number_is_outside_the_demo_range() -> None:
    lookup = load_policy()
    assert not lookup.order_min <= int(EXAMPLE_NUMBER.lstrip("#")) <= lookup.order_max


def test_the_example_email_is_not_in_the_demo_domain() -> None:
    assert EXAMPLE_EMAIL.rpartition("@")[2] != EMAIL_DOMAIN


@pytest.mark.parametrize(
    ("messages", "arguments", "asked"),
    [
        (
            [UserMessage("Where is my order?")],
            {"order_number": EXAMPLE_NUMBER, "email": EXAMPLE_EMAIL},
            "both",
        ),
        (
            [UserMessage(f"Where is my order? {EMAIL}")],
            {"order_number": EXAMPLE_NUMBER, "email": EMAIL},
            "order_number",
        ),
        (
            [UserMessage("Please look up #1042.")],
            {"order_number": "#1042", "email": EXAMPLE_EMAIL},
            "email",
        ),
        (
            [UserMessage(f"Where is #1042? {EMAIL}")],
            {"order_number": EXAMPLE_NUMBER, "email": EMAIL},
            "order_number",
        ),
    ],
    ids=["both_copied", "number_copied", "email_copied", "number_copied_with_both_written"],
)
def test_a_call_that_copies_the_example_values_is_stopped_by_the_guard(
    messages: list[Message], arguments: dict[str, str], asked: str
) -> None:
    subject = rig(tool_call(**arguments))
    result = subject.run(messages)
    assert result.answer == ASKS[asked]
    assert subject.tool.calls == []
    assert internal_of(result)["guard"]["count"] == 1
    assert internal_of(result)["reply_source"] == "template"


def test_an_ask_without_the_examples_is_replaced_by_the_ask_with_them() -> None:
    subject = rig(BARE["both"])
    result = subject.run([UserMessage("Where is my order?")])
    assert result.answer == ASKS["both"]
    event = internal_of(result)["fact_check"]["events"][0]
    assert event["reason"] == "ask_without_example"
    assert event["matched"] == BARE["both"]
    assert internal_of(result)["reply_source"] == "template"


def test_a_bare_ask_for_the_wrong_item_is_replaced_by_the_ask_for_what_is_missing() -> None:
    subject = rig(BARE["email"])
    result = subject.run([UserMessage(f"Where is my order? {EMAIL}")])
    assert result.answer == ASKS["order_number"]
