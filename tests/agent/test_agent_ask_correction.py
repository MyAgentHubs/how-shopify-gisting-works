import pytest
from agent_support import EMAIL, internal_of, rig

from gisting.agent.policy import load_agent_policy
from gisting.prompt.messages import Message, UserMessage

REPLIES = load_agent_policy().needs_input_replies
NOTHING: list[Message] = [UserMessage("Where is my order?")]
EMAIL_ONLY: list[Message] = [UserMessage(f"Has my package shipped? {EMAIL}")]
NUMBER_ONLY: list[Message] = [UserMessage("Please look up #1042.")]


@pytest.mark.parametrize(
    ("said", "messages", "asked"),
    [
        ("both", EMAIL_ONLY, "order_number"),
        ("email", EMAIL_ONLY, "order_number"),
        ("both", NUMBER_ONLY, "email"),
        ("order_number", NUMBER_ONLY, "email"),
        ("email", NOTHING, "both"),
        ("order_number", NOTHING, "both"),
    ],
)
def test_an_ask_for_the_wrong_item_is_replaced_by_the_ask_for_what_is_missing(
    said: str, messages: list[Message], asked: str
) -> None:
    subject = rig(REPLIES[said])
    result = subject.run(messages)
    assert result.answer == REPLIES[asked]
    assert subject.tool.calls == []
    internal = internal_of(result)
    assert internal["reply_source"] == "template"
    event = internal["fact_check"]["events"][0]
    assert event["reason"] == "misdirected_ask"
    assert event["matched"] == REPLIES[said]


@pytest.mark.parametrize(
    ("said", "messages"),
    [("both", NOTHING), ("order_number", EMAIL_ONLY), ("email", NUMBER_ONLY)],
)
def test_the_right_ask_is_left_alone(said: str, messages: list[Message]) -> None:
    result = rig(REPLIES[said]).run(messages)
    assert result.answer == REPLIES[said]
    assert internal_of(result)["reply_source"] == "model"
    assert internal_of(result)["fact_check"] == {"count": 0, "events": []}


def test_an_ask_is_left_alone_when_the_customer_gave_everything() -> None:
    result = rig(REPLIES["email"]).run()
    assert result.answer == REPLIES["email"]
    assert internal_of(result)["fact_check"]["count"] == 0


@pytest.mark.parametrize(
    ("said", "messages", "asked"),
    [
        ("Could you share the email address used for the order?", NOTHING, "both"),
        ("Please send the email used for the order and I will check.", NUMBER_ONLY, "email"),
        ("Can you tell me your order number?", EMAIL_ONLY, "order_number"),
        ("What is your order number and email?", NOTHING, "both"),
        ("I need your email address first.", NUMBER_ONLY, "email"),
    ],
)
def test_an_ask_in_the_models_own_words_is_replaced_by_the_fixed_ask_for_what_is_missing(
    said: str, messages: list[Message], asked: str
) -> None:
    subject = rig(said)
    result = subject.run(messages)
    assert result.answer == REPLIES[asked]
    assert subject.tool.calls == []
    event = internal_of(result)["fact_check"]["events"][0]
    assert event["reason"] == "reworded_ask"
    assert event["matched"] == said
    assert internal_of(result)["reply_source"] == "template"


@pytest.mark.parametrize(
    ("said", "messages"),
    [
        ("Hello! How can I help you with your order today?", NOTHING),
        ("Your order number is on the confirmation page.", NOTHING),
        ("Thanks, I have your email.", EMAIL_ONLY),
    ],
)
def test_a_reply_that_does_not_ask_for_an_order_number_or_email_is_left_alone(
    said: str, messages: list[Message]
) -> None:
    result = rig(said).run(messages)
    assert result.answer == said
    assert internal_of(result)["fact_check"] == {"count": 0, "events": []}
