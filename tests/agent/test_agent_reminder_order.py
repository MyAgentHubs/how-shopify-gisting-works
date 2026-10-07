import json
from collections.abc import Sequence

import pytest
from agent_support import EMAIL, internal_of, rig

from gisting.agent.policy import load_agent_policy
from gisting.prompt.messages import AssistantMessage, Message, ToolCall, ToolMessage, UserMessage
from gisting.prompt.phrases import load_phrases
from gisting.shopify.demo_email import demo_email
from gisting.shopify.jsonvalue import JsonObject

S = load_phrases().sentences
UNSHIPPED = (
    f"Your order has not shipped yet, so I do not have a delivery date. {S['reminder_offer']}"
)
FIRST_EMAIL, SECOND_EMAIL = EMAIL, demo_email("other-secret", "#1043")
ASK_NUMBER = load_agent_policy().needs_input_replies["order_number"]
ASK_EMAIL = load_agent_policy().needs_input_replies["email"]
LOOKUP_CALL = AssistantMessage("", (ToolCall("lookup_order", {"order_number": "#1043"}),))


def found(number: str) -> str:
    order = {"order_number": {"value": number, "source": "shopify"}}
    return json.dumps({"status": "found", "order": order})


TWO_ORDERS: list[Message] = [
    UserMessage(f"Where is #1042? My email is {FIRST_EMAIL}"),
    AssistantMessage(UNSHIPPED),
    UserMessage("no thanks"),
    AssistantMessage(S["decline_ack"]),
    UserMessage(f"OK what about #1043? My email is {SECOND_EMAIL}"),
    AssistantMessage(UNSHIPPED),
    UserMessage("yes please"),
]


def reminder_orders(calls: Sequence[tuple[JsonObject, str]]) -> list[str]:
    return [str(arguments["order_number"]) for arguments, _ in calls]


def test_a_yes_to_the_second_orders_offer_reminds_about_the_second_order() -> None:
    subject = rig()
    result = subject.run(TWO_ORDERS)
    assert reminder_orders(subject.reminder.calls) == ["#1043"]
    assert internal_of(result)["reply_source"] == "code"


def test_the_order_is_the_nearest_one_written_before_the_offer_even_in_an_earlier_message() -> None:
    history: list[Message] = [
        UserMessage(f"Where is my order? My email is {FIRST_EMAIL}"),
        AssistantMessage(ASK_NUMBER),
        UserMessage("#1042"),
        AssistantMessage(UNSHIPPED),
        UserMessage("yes"),
    ]
    subject = rig()
    subject.run(history)
    assert reminder_orders(subject.reminder.calls) == ["#1042"]


def test_a_yes_that_carries_another_number_starts_no_reminder() -> None:
    history: list[Message] = [
        UserMessage(f"Where is #1042? My email is {FIRST_EMAIL}"),
        AssistantMessage(UNSHIPPED),
        UserMessage("yes #1099"),
    ]
    subject = rig("Which order do you mean?")
    subject.run(history)
    assert subject.reminder.calls == []


@pytest.mark.parametrize(
    ("first", "yes", "asked"),
    [
        (f"Where are #1042 and #1043? My email is {FIRST_EMAIL}", "yes #1043", ASK_EMAIL),
        (f"Where is my order? My email is {FIRST_EMAIL}", "yes #1042", ASK_NUMBER),
    ],
    ids=["two_numbers", "no_number"],
)
def test_without_one_clear_order_before_the_offer_the_model_is_asked_to_ask(
    first: str, yes: str, asked: str
) -> None:
    history: list[Message] = [
        UserMessage(first),
        AssistantMessage(UNSHIPPED),
        UserMessage(yes),
    ]
    subject = rig(asked)
    result = subject.run(history)
    assert subject.reminder.calls == []
    assert len(subject.model.prompts) == 1
    assert result.answer == asked


def test_the_order_of_the_latest_found_lookup_result_in_the_history_is_the_one_verified() -> None:
    history: list[Message] = [
        UserMessage(f"Compare #1042 with #1043. My email is {FIRST_EMAIL}"),
        LOOKUP_CALL,
        ToolMessage(found("#1043")),
        AssistantMessage(UNSHIPPED),
        UserMessage("yes"),
    ]
    subject = rig()
    subject.run(history)
    assert reminder_orders(subject.reminder.calls) == ["#1043"]


def test_a_lookup_which_found_nothing_is_not_taken_for_a_verified_order() -> None:
    history: list[Message] = [
        UserMessage(f"Where is #1042? My email is {FIRST_EMAIL}"),
        LOOKUP_CALL,
        ToolMessage(found("#1042")),
        AssistantMessage(UNSHIPPED),
        UserMessage("no"),
        AssistantMessage(S["decline_ack"]),
        UserMessage(f"And #1042 once more? {FIRST_EMAIL}"),
        LOOKUP_CALL,
        ToolMessage('{"status": "no_match"}'),
        AssistantMessage(UNSHIPPED),
        UserMessage("yes"),
    ]
    subject = rig()
    subject.run(history)
    assert reminder_orders(subject.reminder.calls) == ["#1042"]
