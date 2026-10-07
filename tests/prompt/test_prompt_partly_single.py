import pytest
from replies_support import detailed, found

from gisting.prompt.phrases import load_phrases
from gisting.prompt.replies import fixed_reply

PHRASES = load_phrases()
S = PHRASES.sentences
OFFER, THANKS, REST = S["handoff_offer"], S["thanks_patience"], S["unshipped_rest"]
LEAD = "Your order has partly shipped."
FACTS = "it is with Test Parcel, tracking number TP-1, expected delivery October 5."
DAY = "2026-10-03T10:00:00Z"
OPENING = {
    "IN_TRANSIT": "is on its way",
    "OUT_FOR_DELIVERY": "is out for delivery",
    "DELAYED": "is delayed",
    "ATTEMPTED_DELIVERY": "had an unsuccessful delivery attempt",
}
CLOSING = {"DELAYED": f" {THANKS} {REST} {OFFER}", "ATTEMPTED_DELIVERY": f" {REST} {OFFER}"}


def partly(status: str, **parts: str | None) -> str:
    return fixed_reply(PHRASES, found("PARTIALLY_FULFILLED", detailed(status, **parts)))


@pytest.mark.parametrize("status", list(OPENING))
def test_one_parcel_of_a_partly_shipped_order_is_listed_as_the_first_parcel(status: str) -> None:
    expected = f"{LEAD} First parcel {OPENING[status]}: {FACTS}{CLOSING.get(status, f' {REST}')}"
    assert partly(status) == expected


def test_the_approved_example_of_a_delayed_parcel_reads_word_for_word() -> None:
    got = partly("DELAYED", estimated="2026-10-09T10:00:00Z")
    assert got == (
        "Your order has partly shipped. First parcel is delayed: it is with Test Parcel, "
        "tracking number TP-1, expected delivery October 9. Thanks for your patience! "
        "The rest of your items have not shipped yet, and I do not have a date for them. "
        "Would you like me to connect you with a member of our team?"
    )


def test_a_delivered_parcel_says_delivered_on_not_expected_delivery() -> None:
    text = partly("DELIVERED", estimated=None, delivered=DAY)
    assert text == (
        f"{LEAD} First parcel has been delivered: it was sent with Test Parcel, "
        f"tracking number TP-1, delivered on October 3. {REST}"
    )
    assert "Expected delivery" not in text


@pytest.mark.parametrize(
    ("parts", "tail"),
    [
        ({"delivered": None}, ": it was sent with Test Parcel, tracking number TP-1."),
        ({"tracking": None}, ": it was sent with Test Parcel, delivered on October 3."),
        ({"carrier": None}, ": tracking number TP-1, delivered on October 3."),
    ],
)
def test_a_delivered_parcel_missing_details_names_only_what_is_known(
    parts: dict[str, str | None], tail: str
) -> None:
    given = {"estimated": None, "delivered": DAY, **parts}
    assert partly("DELIVERED", **given) == f"{LEAD} First parcel has been delivered{tail} {REST}"


def test_a_delivered_parcel_with_only_a_date_says_when_it_was_delivered() -> None:
    text = partly("DELIVERED", carrier=None, tracking=None, estimated=None, delivered=DAY)
    assert text == f"{LEAD} First parcel was delivered on October 3. {REST}"


def test_a_delivered_parcel_with_no_details_is_only_that_it_was_delivered() -> None:
    text = partly("DELIVERED", carrier=None, tracking=None, estimated=None, delivered=None)
    assert text == f"{LEAD} First parcel has been delivered. {REST}"


def test_a_parcel_missing_the_date_says_so_and_keeps_the_closing_of_its_status() -> None:
    assert partly("DELAYED", estimated=None) == (
        f"{LEAD} First parcel is delayed: it is with Test Parcel, tracking number TP-1, "
        f"but I do not have a delivery date for it yet.{CLOSING['DELAYED']}"
    )
    assert partly("IN_TRANSIT", tracking=None) == (
        f"{LEAD} First parcel is on its way: it is with Test Parcel, expected delivery "
        f"October 5, but I do not have a tracking number for it yet. {REST}"
    )


def test_a_parcel_with_neither_tracking_number_nor_date_keeps_its_status_and_carrier() -> None:
    bare = "First parcel had an unsuccessful delivery attempt: it is with Test Parcel, but I do"
    assert partly("ATTEMPTED_DELIVERY", tracking=None, estimated=None) == (
        f"{LEAD} {bare} not have a tracking number or a delivery date for it yet. {REST} {OFFER}"
    )


def test_a_partly_shipped_order_without_any_parcel_keeps_the_approved_note() -> None:
    assert fixed_reply(PHRASES, found("PARTIALLY_FULFILLED")) == (
        f"{LEAD} {PHRASES.no_shipment_details} {REST}"
    )


def test_a_partly_shipped_order_never_says_the_whole_order_is_delivered() -> None:
    assert "Your order has been delivered" not in partly("DELIVERED", estimated=None, delivered=DAY)


def test_the_partly_shipped_line_in_the_phrases_file_is_only_the_sentence_that_is_rendered() -> (
    None
):
    line = PHRASES.reply_by_status["fulfillment_status"]["PARTIALLY_FULFILLED"]
    assert line.format(words=PHRASES.fulfillment_status["PARTIALLY_FULFILLED"]) == LEAD
