import pytest
from replies_support import detailed, found

from gisting.prompt.phrases import load_phrases
from gisting.prompt.replies import fixed_reply

PHRASES = load_phrases()
S = PHRASES.sentences
OFFER, THANKS = S["handoff_offer"], S["thanks_patience"]
BEGINNING = {
    "IN_TRANSIT": "is on its way",
    "OUT_FOR_DELIVERY": "is out for delivery",
    "DELAYED": "is delayed",
    "ATTEMPTED_DELIVERY": "had an unsuccessful delivery attempt",
}
CLOSING = {"DELAYED": f" {THANKS} {OFFER}", "ATTEMPTED_DELIVERY": f" {OFFER}"}
NO_DATE = "but I do not have a delivery date"
NO_TRACKING = "but I do not have a tracking number"
DELIVERED_AT = "2026-10-03T10:00:00Z"


def first_of_two(status: str, **parts: str | None) -> str:
    text = fixed_reply(
        PHRASES, found("FULFILLED", detailed(status, **parts), detailed("IN_TRANSIT"))
    )
    return text.split(" Second parcel")[0]


def alone(status: str, fulfillment: str = "FULFILLED", **parts: str | None) -> str:
    return fixed_reply(PHRASES, found(fulfillment, detailed(status, **parts)))


@pytest.mark.parametrize("status", list(BEGINNING))
def test_m1_a_parcel_with_a_tracking_number_and_no_date_says_it_has_no_date_yet(
    status: str,
) -> None:
    expected = (
        f"First parcel {BEGINNING[status]}: it is with Test Parcel, tracking number TP-1, "
        f"{NO_DATE} for it yet."
    )
    assert first_of_two(status, estimated=None) == expected


@pytest.mark.parametrize("status", list(BEGINNING))
def test_m2_a_parcel_with_a_date_and_no_tracking_number_says_it_has_no_tracking_number_yet(
    status: str,
) -> None:
    expected = (
        f"First parcel {BEGINNING[status]}: it is with Test Parcel, "
        f"expected delivery October 5, {NO_TRACKING} for it yet."
    )
    assert first_of_two(status, tracking=None) == expected


@pytest.mark.parametrize("status", list(BEGINNING))
def test_m3_a_parcel_without_a_carrier_drops_the_carrier_segment(status: str) -> None:
    expected = (
        f"First parcel {BEGINNING[status]}: tracking number TP-1, expected delivery October 5."
    )
    assert first_of_two(status, carrier=None) == expected


def test_m3_without_a_carrier_the_missing_facts_are_still_named() -> None:
    assert first_of_two("IN_TRANSIT", carrier=None, estimated=None) == (
        f"First parcel is on its way: tracking number TP-1, {NO_DATE} for it yet."
    )
    assert first_of_two("IN_TRANSIT", carrier=None, tracking=None) == (
        f"First parcel is on its way: expected delivery October 5, {NO_TRACKING} for it yet."
    )


NEITHER = "but I do not have a tracking number or a delivery date"


@pytest.mark.parametrize("status", list(BEGINNING))
def test_a_parcel_with_neither_tracking_number_nor_date_keeps_its_own_status_and_carrier(
    status: str,
) -> None:
    text = first_of_two(status, tracking=None, estimated=None)
    assert (
        text == f"First parcel {BEGINNING[status]}: it is with Test Parcel, {NEITHER} for it yet."
    )


@pytest.mark.parametrize("status", list(BEGINNING))
def test_a_bare_parcel_without_a_carrier_is_its_status_then_what_is_missing(status: str) -> None:
    text = first_of_two(status, carrier=None, tracking=None, estimated=None)
    assert text == f"First parcel {BEGINNING[status]}, {NEITHER} for it yet."


def test_a_bare_shipped_parcel_keeps_its_carrier_among_several() -> None:
    assert first_of_two("FULFILLED", tracking=None, estimated=None) == (
        f"First parcel has shipped: it is with Test Parcel, {NEITHER} for it yet."
    )


def test_m4_a_shipped_parcel_with_a_tracking_number_does_not_claim_there_is_none() -> None:
    assert first_of_two("FULFILLED", estimated=None) == (
        "First parcel has shipped: it is with Test Parcel, tracking number TP-1, "
        f"{NO_DATE} for it yet."
    )


def test_m4_with_a_date_and_no_tracking_number_it_says_the_tracking_number_is_missing() -> None:
    assert first_of_two("FULFILLED", tracking=None) == (
        "First parcel has shipped: it is with Test Parcel, expected delivery October 5, "
        f"{NO_TRACKING} for it yet."
    )


def test_m5_a_delivered_parcel_missing_everything_is_just_delivered() -> None:
    text = first_of_two("DELIVERED", carrier=None, tracking=None, estimated=None)
    assert text == "First parcel has been delivered."


@pytest.mark.parametrize(
    ("parts", "tail"),
    [
        ({"delivered": None}, ": it was sent with Test Parcel, tracking number TP-1."),
        ({"tracking": None}, ": it was sent with Test Parcel, delivered on October 3."),
        ({"carrier": None}, ": tracking number TP-1, delivered on October 3."),
        ({"carrier": None, "delivered": None}, ": tracking number TP-1."),
        ({"tracking": None, "delivered": None}, ": it was sent with Test Parcel."),
    ],
)
def test_m5_a_delivered_parcel_names_only_what_is_known(
    parts: dict[str, str | None], tail: str
) -> None:
    given = {"delivered": "2026-10-03T10:00:00Z", "estimated": None, **parts}
    assert first_of_two("DELIVERED", **given) == f"First parcel has been delivered{tail}"


def test_m5_a_delivered_parcel_with_only_a_date_says_when_it_was_delivered() -> None:
    given = {"carrier": None, "tracking": None, "estimated": None, "delivered": DELIVERED_AT}
    assert first_of_two("DELIVERED", **given) == "First parcel was delivered on October 3."


def test_m5_the_date_only_sentence_names_each_parcel_by_its_place() -> None:
    given = {"carrier": None, "tracking": None, "estimated": None, "delivered": DELIVERED_AT}
    text = fixed_reply(
        PHRASES, found("FULFILLED", detailed("DELIVERED", **given), detailed("DELIVERED", **given))
    )
    assert text == (
        "First parcel was delivered on October 3. Second parcel was delivered on October 3."
    )


def test_m5_a_single_delivered_order_with_only_a_date_says_when_it_was_delivered() -> None:
    got = alone("DELIVERED", carrier=None, tracking=None, estimated=None, delivered=DELIVERED_AT)
    assert got == "Your order was delivered on October 3."


@pytest.mark.parametrize(
    "parts",
    [{"carrier": None, "delivered": None}, {"tracking": None, "carrier": "Test Parcel"}],
)
def test_m5_a_delivered_parcel_with_a_carrier_or_tracking_number_keeps_the_has_been_delivered_line(
    parts: dict[str, str | None],
) -> None:
    given: dict[str, str | None] = {"estimated": None, "delivered": DELIVERED_AT, **parts}
    assert "has been delivered:" in first_of_two("DELIVERED", **given)


def test_m5_a_delivered_parcel_never_gets_the_tracking_reassurance() -> None:
    text = fixed_reply(PHRASES, found("FULFILLED", detailed("DELIVERED", None, None, None, None)))
    assert text == "Your order has been delivered."
    assert "tracking usually appears" not in text


@pytest.mark.parametrize("status", list(BEGINNING))
def test_single_m1_has_no_for_it_and_keeps_the_closing_of_the_status(status: str) -> None:
    expected = (
        f"Your order {BEGINNING[status]}: it is with Test Parcel, tracking number TP-1, "
        f"{NO_DATE} yet.{CLOSING.get(status, '')}"
    )
    assert alone(status, estimated=None) == expected


@pytest.mark.parametrize("status", list(BEGINNING))
def test_single_m2_has_no_for_it(status: str) -> None:
    expected = (
        f"Your order {BEGINNING[status]}: it is with Test Parcel, "
        f"expected delivery October 5, {NO_TRACKING} yet.{CLOSING.get(status, '')}"
    )
    assert alone(status, tracking=None) == expected


@pytest.mark.parametrize("status", list(BEGINNING))
def test_single_m3_drops_the_carrier_segment(status: str) -> None:
    expected = (
        f"Your order {BEGINNING[status]}: tracking number TP-1, "
        f"expected delivery October 5.{CLOSING.get(status, '')}"
    )
    assert alone(status, carrier=None) == expected


def test_single_m4_a_shipped_order_with_a_tracking_number_does_not_claim_there_is_none() -> None:
    assert alone("FULFILLED", estimated=None) == (
        f"Your order has shipped: it is with Test Parcel, tracking number TP-1, {NO_DATE} yet."
    )


def test_single_m5_a_delivered_order_names_only_what_is_known() -> None:
    got = alone("DELIVERED", estimated=None, tracking=None, delivered="2026-10-03T10:00:00Z")
    assert (
        got
        == "Your order has been delivered: it was sent with Test Parcel, delivered on October 3."
    )


def test_a_single_parcel_with_every_fact_keeps_the_original_sentences() -> None:
    assert alone("IN_TRANSIT") == (
        "Your order is on its way. It is with Test Parcel, tracking number TP-1. "
        "Expected delivery: October 5."
    )
    assert alone("DELIVERED", estimated=None, delivered="2026-10-03T10:00:00Z") == (
        "Your order has been delivered. It was sent with Test Parcel, tracking number TP-1. "
        "Delivered on October 3."
    )


@pytest.mark.parametrize("status", list(BEGINNING))
def test_a_single_bare_parcel_keeps_its_status_and_carrier_and_the_closing(status: str) -> None:
    assert alone(status, tracking=None, estimated=None) == (
        f"Your order {BEGINNING[status]}: it is with Test Parcel, {NEITHER} yet."
        f"{CLOSING.get(status, '')}"
    )


@pytest.mark.parametrize("status", list(BEGINNING))
def test_a_single_bare_parcel_without_a_carrier_is_its_status_then_what_is_missing(
    status: str,
) -> None:
    assert alone(status, carrier=None, tracking=None, estimated=None) == (
        f"Your order {BEGINNING[status]}, {NEITHER} yet.{CLOSING.get(status, '')}"
    )


def test_a_single_bare_shipped_parcel_keeps_the_no_shipment_details_sentence() -> None:
    assert alone("FULFILLED", tracking=None, estimated=None) == (
        f"Your order has shipped. {S['no_shipment_details']} {OFFER}"
    )
