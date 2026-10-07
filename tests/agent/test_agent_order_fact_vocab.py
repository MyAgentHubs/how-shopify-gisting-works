import pytest
from agent_support import internal_of, rig

from gisting.prompt.messages import Message, UserMessage

WHERE: list[Message] = [UserMessage("Where is my order?")]
SUNDAYS: list[Message] = [UserMessage("Do you deliver on Sundays?")]


@pytest.mark.parametrize(
    "said",
    [
        "Your parcel is being packed.",
        "Your order is on hold.",
        "Your order was cancelled.",
        "Your order was canceled.",
        "Your order was picked up.",
        "Your order is ready for pickup.",
        "Your package left our warehouse.",
        "Your order is processing.",
        "The parcel is expected to arrive on Monday.",
        "Your order is scheduled for delivery.",
        "Yes, we deliver on Saturdays.",
    ],
)
def test_an_order_stage_or_arrival_claim_without_a_tool_result_is_replaced_by_the_ask(
    said: str,
) -> None:
    subject = rig(said)
    result = subject.run(WHERE)
    assert result.answer != said
    assert subject.tool.calls == []
    internal = internal_of(result)
    assert internal["reply_source"] == "template"
    assert internal["fact_check"]["count"] == 1


@pytest.mark.parametrize(
    ("said", "asked"),
    [
        ("I don't have information about when #1027 will arrive.", "Where is #1027?"),
        ("I cannot determine the carrier for order #1031.", "Which carrier has #1031?"),
        ("Sorry, I do not have that information.", "Where is my order?"),
        ("Hello! How can I help with your order today?", "Where is my order?"),
        ("I don't know when it is expected to arrive.", "Where is my order?"),
    ],
)
def test_a_refusal_or_greeting_that_asserts_no_order_fact_passes_unchanged(
    said: str, asked: str
) -> None:
    result = rig(said).run([UserMessage(asked)])
    assert result.answer == said
    assert internal_of(result)["fact_check"]["count"] == 0


def test_a_weekday_the_user_named_in_the_plural_is_not_an_invented_one() -> None:
    said = "Yes, we deliver on Sundays."
    result = rig(said).run(SUNDAYS)
    assert result.answer == said
    assert internal_of(result)["fact_check"]["count"] == 0
