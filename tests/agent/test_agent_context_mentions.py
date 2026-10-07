import pytest
from agent_support import EMAIL, SECRET

from gisting.agent.context import without_earlier_orders
from gisting.agent.policy import load_agent_policy
from gisting.prompt.messages import AssistantMessage, Message, UserMessage
from gisting.shopify.demo_email import demo_email
from gisting.tools.policy import load_policy

POLICY = load_agent_policy()
LOOKUP = load_policy()
PLACEHOLDER = POLICY.dropped_placeholder
REPLY_A = (
    "Your order is on its way. It is with Test Parcel, tracking number TP-1042. "
    "Expected delivery: October 5."
)
ASK_A = f"Where is order #1042? My email is {EMAIL}"
SPELLINGS = [
    "No.{n}",
    "order:{n}",
    "order-{n}",
    "order_{n}",
    "order{n}",
    "order#{n}",
    "order number:{n}",
    "ORD-{n}",
    "Order No.{n}",
    "{n}/1",
    "#{n}abc",
    "order {n} items",
    "{n} usd",
    "{n}kg",
    "({n})",
    "Order # {n}",
    "id​{n}",
    "＃{n}",
    "＃{wide}",
    "{wide}",
    "order {wide} items",
    "{arabic}",
]


def spelled(template: str, number: int) -> str:
    wide = str(number).translate({ord("0") + i: ord("０") + i for i in range(10)})
    arabic = str(number).translate({ord("0") + i: ord("٠") + i for i in range(10)})
    return template.format(n=number, wide=wide, arabic=arabic)


def after_a(text: str) -> list[Message]:
    history: list[Message] = [UserMessage(ASK_A), AssistantMessage(REPLY_A), UserMessage(text)]
    return without_earlier_orders(POLICY, LOOKUP, history).messages


@pytest.mark.parametrize("template", SPELLINGS)
def test_any_spelling_of_another_in_range_order_drops_the_earlier_order(template: str) -> None:
    text = f"where is {spelled(template, 1043)}?"
    assert after_a(text) == [
        UserMessage(PLACEHOLDER),
        AssistantMessage(PLACEHOLDER),
        UserMessage(text),
    ]


@pytest.mark.parametrize("template", SPELLINGS)
def test_any_spelling_of_the_same_order_keeps_the_history(template: str) -> None:
    text = f"where is {spelled(template, 1042)}?"
    assert after_a(text)[:2] == [UserMessage(ASK_A), AssistantMessage(REPLY_A)]


@pytest.mark.parametrize("text", ["#9999", "＃９９９９", "order #12345678"])
def test_a_hash_number_anywhere_is_a_switch(text: str) -> None:
    assert after_a(text)[0] == UserMessage(PLACEHOLDER)


@pytest.mark.parametrize(
    "text", ["it was 3 weeks ago", "about 2026", "order 0", "x" * 40, "a" + "9" * 30]
)
def test_digits_outside_the_range_without_a_hash_are_not_a_switch(text: str) -> None:
    assert after_a(text)[0] == UserMessage(ASK_A)


def test_digits_inside_an_email_are_not_an_order_mention() -> None:
    other = demo_email(SECRET, "#1042").replace("@", "1043@")
    assert after_a(f"use {other}")[0] == UserMessage(PLACEHOLDER)
    assert after_a(f"use {EMAIL}")[0] == UserMessage(ASK_A)
