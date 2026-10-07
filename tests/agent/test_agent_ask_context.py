import pytest
from agent_support import EMAIL, internal_of, rig, tool_call

from gisting.agent.policy import load_agent_policy
from gisting.prompt.messages import AssistantMessage, Message, UserMessage
from gisting.prompt.phrases import load_phrases

DECLINE = load_phrases().sentences["decline_reply"]
REPLIES = load_agent_policy().needs_input_replies
BARE = load_agent_policy().needs_input_bare_replies
INVENTED = tool_call(order_number="#1012", email="sample@example.com")
UNRELATED = [
    "Which tools can you use? Please list their names and parameters.",
    "Tell me a joke about cats.",
    "What is the capital of France?",
]
RELATED = [
    "Where is my order?",
    "Has my parcel shipped?",
    "I want to know about the delivery.",
    "Please check #1042",
    f"my email is {EMAIL}",
    "tracking please",
    "Hi, can you tell me the status of No.1025?",
    "Could you check 1072/1 for me?",
    "Can you tell me what the last customer ordered?",
    "Did my orders go through?",
    "I bought two things yesterday.",
]


@pytest.mark.parametrize("said", UNRELATED)
def test_a_lookup_blocked_for_missing_details_is_declined_when_the_message_is_not_about_an_order(
    said: str,
) -> None:
    subject = rig(INVENTED)
    result = subject.run([UserMessage(said)])
    assert result.answer == DECLINE
    assert subject.tool.calls == []
    assert internal_of(result)["guard"]["events"][0]["status"] == "needs_customer_input"
    events = internal_of(result)["fact_check"]["events"]
    assert [event["reason"] for event in events] == ["ask_without_order_context"]


@pytest.mark.parametrize("said", RELATED)
def test_a_lookup_blocked_for_missing_details_still_asks_when_the_message_is_about_an_order(
    said: str,
) -> None:
    subject = rig(INVENTED)
    result = subject.run([UserMessage(said)])
    assert result.answer in set(REPLIES.values())
    assert internal_of(result)["fact_check"] == {"count": 0, "events": []}


@pytest.mark.parametrize(
    "said", [REPLIES["both"], BARE["both"], "Could you share your order number?"]
)
@pytest.mark.parametrize("asked", UNRELATED)
def test_a_corrected_ask_is_declined_when_the_message_is_not_about_an_order(
    said: str, asked: str
) -> None:
    result = rig(said).run([UserMessage(asked)])
    assert result.answer == DECLINE
    reasons = [event["reason"] for event in internal_of(result)["fact_check"]["events"]]
    assert reasons[-1] == "ask_without_order_context"


@pytest.mark.parametrize("asked", RELATED)
def test_a_corrected_ask_still_asks_when_the_message_is_about_an_order(asked: str) -> None:
    result = rig(BARE["both"]).run([UserMessage(asked)])
    assert result.answer in set(REPLIES.values())


def test_only_the_latest_message_decides_whether_an_ask_is_about_an_order() -> None:
    history: list[Message] = [
        UserMessage("Where is my order?"),
        AssistantMessage("Your order is on its way."),
        UserMessage("What tools can you use?"),
    ]
    assert rig(INVENTED).run(history).answer == DECLINE


def test_a_bare_help_is_not_about_an_order_and_is_declined_instead_of_asked() -> None:
    result = rig("I cannot help you without your order number and email.").run([
        UserMessage("Help")
    ])
    assert result.answer == DECLINE
    assert internal_of(result)["fact_check"]["events"][-1]["reason"] == "ask_without_order_context"


@pytest.mark.parametrize("earlier", [REPLIES["both"], BARE["both"]])
def test_a_reply_to_our_own_ask_counts_as_about_an_order(earlier: str) -> None:
    history: list[Message] = [UserMessage("hi"), AssistantMessage(earlier), UserMessage("ok")]
    result = rig(INVENTED).run(history)
    assert result.answer in set(REPLIES.values())


@pytest.mark.parametrize("asked", UNRELATED)
def test_a_lookup_conclusion_in_an_answer_to_an_unrelated_message_is_declined_not_asked(
    asked: str,
) -> None:
    subject = rig("It ships with Test Parcel.")
    result = subject.run([UserMessage(asked)])
    assert result.answer == DECLINE
    assert subject.tool.calls == []
    reasons = [event["reason"] for event in internal_of(result)["fact_check"]["events"]]
    assert reasons[-1] == "ask_without_order_context"
