import pytest
from replies_support import found, shipment

from gisting.prompt.phrases import load_phrases
from gisting.prompt.replies import fixed_reply

PHRASES = load_phrases()
S = PHRASES.sentences


def test_one_shipment_is_the_status_line_filled_in_with_a_date_that_has_no_year() -> None:
    text = fixed_reply(PHRASES, found("FULFILLED", shipment("IN_TRANSIT")))
    assert text == (
        "Your order is on its way. It is with Test Parcel, tracking number TP-1. "
        "Expected delivery: October 5."
    )
    assert "2026" not in text


def test_a_delayed_shipment_ends_with_the_thanks_and_the_handoff_offer() -> None:
    text = fixed_reply(PHRASES, found("FULFILLED", shipment("DELAYED")))
    assert text.endswith(f"{S['thanks_patience']} {S['handoff_offer']}")


def test_an_unshipped_order_gets_the_reminder_offer_line() -> None:
    text = fixed_reply(PHRASES, found("UNFULFILLED"))
    assert text == (
        f"Your order has not shipped yet, so I do not have a delivery date. {S['reminder_offer']}"
    )


def test_a_shipment_without_tracking_gets_the_but_sentence_and_the_handoff_offer() -> None:
    text = fixed_reply(PHRASES, found("FULFILLED", shipment("FULFILLED", None, None)))
    assert text == f"Your order has shipped. {S['no_shipment_details']} {S['handoff_offer']}"


@pytest.mark.parametrize("status", ["no_match", "unavailable", "locked"])
def test_every_failure_status_uses_the_failure_reply_from_the_data(status: str) -> None:
    assert fixed_reply(PHRASES, {"status": status}) == PHRASES.failure_replies[status]


def test_the_parcel_copy_and_ordinals_come_from_the_data() -> None:
    assert PHRASES.parcels.forms["several"].subject == "{ordinal} parcel"
    assert PHRASES.parcels.ordinals[:2] == ("First", "Second")
    assert PHRASES.parcels.status.keys() == PHRASES.transport_status.keys()
