import json

import pytest
from agent_support import EMAIL, QUESTION, RENDERED, SECRET, good_call, internal_of, rig

from gisting.agent.checks import earlier_reply_texts
from gisting.agent.policy import FallbackReason, load_agent_policy
from gisting.agent.time_claims import TimeRules, load_time_rules, unsupported_claims
from gisting.prompt.messages import AssistantMessage, Message, UserMessage
from gisting.shopify.demo_email import demo_email

POLICY = load_agent_policy()
ASK_BOTH = POLICY.needs_input_replies["both"]
NO_ORDER_YET: list[Message] = [UserMessage("Where is my order?")]
ARRIVALS = [
    "Your order will arrive on Tuesday.",
    "Expect it around October 7.",
    "It should be there tomorrow.",
    "Your order arrives on the 7th of October.",
    "It will be with you by Friday.",
    "Delivery usually takes 1-5 business days.",
    "Sure! Your order arrives in two days.",
    "It ships tonight.",
    "Look out for it next week.",
    "It should arrive within 3 days.",
    "Your order #2077 looks fine.",
    "It arrives Thurs, Oct. 8th.",
]
RULES: TimeRules = load_time_rules()


@pytest.mark.parametrize("said", ARRIVALS)
def test_a_time_claim_with_no_support_is_replaced_by_the_ask(said: str) -> None:
    subject = rig(said)
    result = subject.run(NO_ORDER_YET)
    assert result.answer == ASK_BOTH
    internal = internal_of(result)
    assert internal["reply_source"] == "template"
    assert internal["fact_check"]["events"][0]["reason"] == "unsupported_time_claim"
    assert internal["model_calls"][0]["raw_output"] == said


@pytest.mark.parametrize("said", ARRIVALS)
def test_a_time_claim_with_the_order_known_falls_back_and_is_counted(said: str) -> None:
    subject = rig(said)
    result = subject.run([UserMessage("Is order #1042 late? My email is " + EMAIL)])
    assert result.fallback_reason is FallbackReason.UNCHECKED_CONCLUSION
    assert result.answer == POLICY.fallback_replies[FallbackReason.UNCHECKED_CONCLUSION]
    internal = internal_of(result)
    assert internal["reply_source"] == "fallback"
    assert internal["fact_check"]["events"][0]["reason"] == "unsupported_time_claim"


@pytest.mark.parametrize(
    ("said", "user"),
    [
        ("You mentioned October 7, I can check that.", "It was due Oct 7th, where is it?"),
        ("Since you asked about Tuesday, let me help.", "Is it coming on tuesday?"),
        ("You said it was ordered yesterday.", "I ordered it yesterday and nothing came"),
        ("Order 1042 noted.", "What about 1042?"),
        ("Within 3 days, understood.", "Can it come within 3 days?"),
    ],
)
def test_a_date_the_customer_wrote_may_be_repeated(said: str, user: str) -> None:
    result = rig(said).run([UserMessage(user)])
    assert result.answer == said
    assert internal_of(result)["fact_check"]["count"] == 0


def test_a_question_is_not_a_claim_but_a_tagged_statement_is() -> None:
    assert unsupported_claims(RULES, "How can I help you today?", []) == []
    assert unsupported_claims(RULES, "Sure, would you like it on Friday?", []) == []
    assert unsupported_claims(RULES, "It arrives tomorrow, right?", []) == ["tomorrow"]


def test_the_asking_template_with_its_examples_passes() -> None:
    result = rig(ASK_BOTH).run(NO_ORDER_YET)
    assert result.answer == ASK_BOTH
    assert internal_of(result)["fact_check"]["count"] == 0


def test_a_rendered_reply_is_not_checked() -> None:
    result = rig(good_call()).run([UserMessage(QUESTION)])
    assert result.answer == RENDERED
    internal = internal_of(result)
    assert internal["reply_source"] == "code"
    assert internal["fact_check"]["count"] == 0


def test_a_date_in_a_tool_result_supports_the_same_day_only() -> None:
    tool = json.dumps({"estimated_delivery": "2026-10-05T10:00:00Z"})
    assert unsupported_claims(RULES, "Expect October 5.", [tool]) == []
    assert unsupported_claims(RULES, "Expect October 6.", [tool]) == ["October 6"]


def test_a_weekday_worked_out_from_a_date_is_not_support() -> None:
    tool = json.dumps({"estimated_delivery": "2026-10-05T10:00:00Z"})
    assert unsupported_claims(RULES, "Expect October 5, a Monday.", [tool]) == ["Monday"]
    assert unsupported_claims(RULES, "Expect Tuesday.", [tool]) == ["Tuesday"]


def test_a_weekday_named_in_a_source_supports_the_same_weekday() -> None:
    assert unsupported_claims(RULES, "Yes, Monday works.", ["is it Monday?"]) == []
    assert unsupported_claims(RULES, "Yes, Tuesday works.", ["is it Monday?"]) == ["Tuesday"]


def test_a_number_needs_the_same_digits_in_a_source() -> None:
    assert unsupported_claims(RULES, "Order 1042 and 5 items.", ["#1042"]) == []
    assert unsupported_claims(RULES, "Order 1043.", ["#1042"]) == ["1043"]


FOLLOW_UP = [
    UserMessage(QUESTION),
    AssistantMessage(RENDERED),
    UserMessage("when was it due again?"),
]


def test_a_date_in_an_earlier_reply_still_in_the_input_may_be_repeated() -> None:
    said = "It was due on October 5."
    result = rig(said).run(list(FOLLOW_UP))
    assert result.answer == said
    assert internal_of(result)["fact_check"]["count"] == 0


def test_only_replies_before_the_latest_customer_message_are_support() -> None:
    history: list[Message] = [UserMessage("hi"), AssistantMessage("a"), UserMessage("b")]
    assert earlier_reply_texts([*history, AssistantMessage("c")]) == ["a"]


def test_a_date_from_a_dropped_order_is_not_support() -> None:
    other = f"And order #1043? My email is {demo_email(SECRET, '#1043')}"
    history: list[Message] = [*FOLLOW_UP[:2], UserMessage(other)]
    said = "Order 1043 was due on October 5."
    result = rig(said).run(history)
    assert result.answer != said
    assert internal_of(result)["fact_check"]["events"][0]["reason"] == "unsupported_time_claim"


def test_a_relative_time_no_source_gave_is_still_replaced_with_history() -> None:
    result = rig("It should be there tomorrow.").run(list(FOLLOW_UP))
    assert result.answer != "It should be there tomorrow."
    assert internal_of(result)["fact_check"]["events"][0]["reason"] == "unsupported_time_claim"


AMOUNTS = [
    "Canada shipping costs $12.95. Anything else?",
    "The fee is 5.99",
    "Express costs €8",
    "That's a 15% discount",
    "It comes to 12.95 USD.",
    "Shipping is CAD 5.",
]


@pytest.mark.parametrize("said", AMOUNTS)
def test_an_amount_or_decimal_with_no_support_is_replaced_by_the_ask(said: str) -> None:
    result = rig(said).run(NO_ORDER_YET)
    assert result.answer == ASK_BOTH
    internal = internal_of(result)
    assert internal["reply_source"] == "template"
    assert internal["fact_check"]["events"][0]["reason"] == "unsupported_time_claim"


@pytest.mark.parametrize(
    ("said", "user"),
    [
        ("Yes, $12.95 is what you saw.", "Is $12.95 the shipping fee?"),
        ("The 12.9 fee is noted.", "Is shipping 12.90?"),
        ("Your order #1042 is noted.", "Where is #1042?"),
        ("Hello!", "hi"),
        ("It was 3:30 and version 1.2.3 of the page.", "hi"),
    ],
)
def test_an_amount_the_customer_wrote_or_no_amount_at_all_passes(said: str, user: str) -> None:
    result = rig(said).run([UserMessage(user)])
    assert result.answer == said
    assert internal_of(result)["fact_check"]["count"] == 0


def test_an_amount_is_compared_by_value_not_by_spelling() -> None:
    assert unsupported_claims(RULES, "It is $12.95.", ["shipping 12.95"]) == []
    assert unsupported_claims(RULES, "It is 12.90 USD.", ["costs €12.9"]) == []
    assert unsupported_claims(RULES, "It is $1,200.00.", ["USD 1200"]) == []
    assert unsupported_claims(RULES, "It is $12.96.", ["shipping 12.95"]) == ["$12.96"]
    assert unsupported_claims(RULES, "I can't share pricing.", []) == []


def test_an_amount_in_a_tool_result_supports_a_repeat() -> None:
    tool = json.dumps({"results": [{"text": "Shipping to Canada costs $12.95."}]})
    assert unsupported_claims(RULES, "Canada shipping costs $12.95.", [tool]) == []
    assert unsupported_claims(RULES, "A 15% restocking fee applies.", [tool]) == ["15%"]
