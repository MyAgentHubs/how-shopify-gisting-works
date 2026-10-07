import pytest
from replies_support import detailed, found

from gisting.prompt.parcel_render import month_day
from gisting.prompt.phrases import load_phrases
from gisting.prompt.replies import fixed_reply

PHRASES = load_phrases()
READABLE = [
    "2026-10-05T10:00:00Z",
    "2026-10-05T10:00:00.000Z",
    "2026-10-05T10:00:00+00:00",
    "2026-10-05T10:00:00",
    "2026-10-05",
]
UNREADABLE = ["soon", "2026-13-40", "10/05/2026", "", "   "]
NO_DATE = (
    "Your order is on its way: it is with Test Parcel, tracking number TP-1, "
    "but I do not have a delivery date yet."
)


@pytest.mark.parametrize("stamp", READABLE)
def test_every_iso_8601_form_reads_as_month_and_day_without_a_year(stamp: str) -> None:
    assert month_day(stamp) == "October 5"
    text = fixed_reply(PHRASES, found("FULFILLED", detailed("IN_TRANSIT", estimated=stamp)))
    assert text.endswith("Expected delivery: October 5.")
    assert "2026" not in text


@pytest.mark.parametrize("stamp", UNREADABLE)
def test_an_unreadable_stamp_counts_as_no_date_and_does_not_raise(stamp: str) -> None:
    assert month_day(stamp) is None
    node = detailed("IN_TRANSIT", estimated=stamp)
    assert fixed_reply(PHRASES, found("FULFILLED", node)) == NO_DATE


@pytest.mark.parametrize("value", [5, 1.5, ["2026-10-05"], {"day": 5}, True])
def test_a_stamp_that_is_not_a_string_counts_as_no_date(value: object) -> None:
    node = detailed("IN_TRANSIT")
    node["estimated_delivery"] = {"value": value, "source": "shopify"}
    assert fixed_reply(PHRASES, found("FULFILLED", node)) == NO_DATE


def test_a_delivered_parcel_with_an_unreadable_stamp_just_leaves_the_date_out() -> None:
    node = detailed("DELIVERED", estimated=None, delivered="yesterday")
    assert fixed_reply(PHRASES, found("FULFILLED", node)) == (
        "Your order has been delivered: it was sent with Test Parcel, tracking number TP-1."
    )
