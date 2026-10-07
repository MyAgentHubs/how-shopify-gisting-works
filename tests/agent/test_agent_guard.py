import json

import pytest
from agent_support import (
    EMAIL,
    QUESTION,
    RENDERED,
    SESSION,
    good_call,
    internal_of,
    public_of,
    rig,
    tool_call,
)

from gisting.agent.policy import load_agent_policy
from gisting.prompt.messages import AssistantMessage, Message, UserMessage
from gisting.prompt.phrases import load_phrases

ANSWER = "Your order #1042 is in transit with Test Parcel."
REPLIES = load_agent_policy().needs_input_replies
ASK_EMAIL, ASK_NUMBER, ASK_BOTH = REPLIES["email"], REPLIES["order_number"], REPLIES["both"]


@pytest.mark.parametrize(
    ("messages", "call"),
    [
        ([UserMessage("Please look up #1042.")], tool_call(order_number="#1042", email="")),
        (
            [UserMessage("Please look up #1042.")],
            tool_call(order_number="#1042", email="customer@example.com"),
        ),
        (
            [
                UserMessage("Where is #1042?"),
                AssistantMessage(f"Is your email {EMAIL}?"),
                UserMessage("Please look up #1042."),
            ],
            good_call(),
        ),
    ],
    ids=["empty", "invented", "only_in_assistant_message"],
)
def test_an_email_the_customer_never_wrote_never_reaches_the_tool(
    messages: list[Message], call: str
) -> None:
    subject = rig(call)
    result = subject.run(messages)
    assert result.answer == ASK_EMAIL
    assert result.fallback_reason is None
    assert subject.tool.calls == []
    assert subject.attempts.failures(SESSION) == 0
    assert len(subject.model.prompts) == 1


def test_a_missing_order_number_is_reported_and_does_not_count_as_a_failure() -> None:
    subject = rig(tool_call(order_number="#1042", email=EMAIL))
    result = subject.run([UserMessage(f"My email is {EMAIL}, where is my order?")])
    assert result.answer == ASK_NUMBER
    assert subject.tool.calls == []
    assert subject.attempts.failures(SESSION) == 0
    assert len(subject.model.prompts) == 1


def test_both_inputs_can_be_missing_at_once() -> None:
    subject = rig(tool_call(order_number="#1042", email="a@b.c"))
    result = subject.run([UserMessage("Where is my parcel?")])
    assert result.answer == ASK_BOTH
    assert len(subject.model.prompts) == 1
    assert internal_of(result)["guard"]["events"][0]["missing"] == ["order_number", "email"]


@pytest.mark.parametrize("written", ["1042", "#1042", "order 1042.", "No. 1042,"])
def test_the_order_number_digits_must_stand_alone_in_a_user_message(written: str) -> None:
    subject = rig(good_call(), ANSWER)
    result = subject.run([UserMessage(f"{written} {EMAIL}")])
    assert result.answer == RENDERED
    assert len(subject.tool.calls) == 1


@pytest.mark.parametrize("written", ["#10420", "#21042", "#1043"])
def test_digits_inside_a_longer_number_do_not_ground_the_order_number(written: str) -> None:
    subject = rig(good_call())
    result = subject.run([UserMessage(f"{written} {EMAIL}")])
    assert result.answer == ASK_NUMBER
    assert subject.tool.calls == []


def test_an_email_from_an_earlier_user_message_still_counts() -> None:
    history: list[Message] = [
        UserMessage(f"My email is {EMAIL}"),
        AssistantMessage("Thanks."),
        UserMessage("#1042"),
    ]
    subject = rig(good_call(), ANSWER)
    assert subject.run(history).answer == RENDERED
    assert len(subject.tool.calls) == 1


def test_a_verified_call_is_not_blocked_and_leaves_no_guard_event() -> None:
    result = rig(good_call(), ANSWER).run()
    assert internal_of(result)["guard"] == {"count": 0, "events": []}


def test_guard_events_are_counted_in_the_internal_trace_only() -> None:
    forged = tool_call(order_number="#1042", email="customer@example.com")
    result = rig(forged).run([UserMessage("Please look up #1042.")])
    assert internal_of(result)["guard"] == {
        "count": 1,
        "events": [
            {
                "tool": "lookup_order",
                "arguments": {"order_number": "#1042", "email": "customer@example.com"},
                "status": "needs_customer_input",
                "missing": ["email"],
            }
        ],
    }
    assert internal_of(result)["reply_source"] == "template"
    public = json.dumps(result.traces.public)
    for word in ("guard", "needs_customer_input", "reply_source", "template", "fact_check"):
        assert word not in public
    assert public_of(result)["tools"] == []


def test_a_blocked_call_ends_the_turn_and_the_model_is_not_asked_again() -> None:
    forged = tool_call(order_number="#1042", email="customer@example.com")
    subject = rig(forged, "unused", "unused")
    result = subject.run([UserMessage("Please look up #1042.")])
    assert result.answer == ASK_EMAIL
    assert len(subject.model.prompts) == 1
    assert subject.model.outputs == ["unused", "unused"]
    assert internal_of(result)["guard"]["count"] == 1
    assert len(internal_of(result)["model_calls"]) == 1


def test_one_blocked_call_stops_the_other_calls_in_the_same_output() -> None:
    two_calls = tool_call("send_shipping_reminder", order_number="#1042") + tool_call(
        "handoff_to_human"
    )
    subject = rig(two_calls, max_tool_calls=2)
    result = subject.run([UserMessage(f"{QUESTION} I want to talk to a human")])
    assert result.answer == load_phrases().sentences["decline_reply"]
    assert subject.handoff.calls == []
    assert subject.reminder.calls == []
    assert internal_of(result)["guard"]["count"] == 1


def test_a_model_answer_without_a_call_is_marked_as_coming_from_the_model() -> None:
    result = rig("Hello! How can I help with your order?").run()
    assert internal_of(result)["reply_source"] == "model"
