import pytest
from replies_support import detailed, found

from gisting.prompt.phrases import load_phrases
from gisting.prompt.replies import fixed_reply

PHRASES = load_phrases()
OFFER = PHRASES.handoff_offer


def shipped(**parts: str | None) -> str:
    return fixed_reply(PHRASES, found("FULFILLED", detailed("FULFILLED", **parts)))


@pytest.mark.parametrize(
    ("parts", "line"),
    [
        (
            {},
            "Your order has shipped: it is with Test Parcel, tracking number TP-1, "
            "expected delivery October 5.",
        ),
        (
            {"estimated": None},
            "Your order has shipped: it is with Test Parcel, tracking number TP-1, "
            "but I do not have a delivery date yet.",
        ),
    ],
    ids=["full", "no_date"],
)
def test_one_shipped_parcel_with_a_tracking_number_gets_no_handoff_offer(
    parts: dict[str, str | None], line: str
) -> None:
    assert shipped(**parts) == line


@pytest.mark.parametrize(
    "parts",
    [{"tracking": None}, {"tracking": None, "estimated": None, "carrier": None}],
    ids=["date_without_tracking", "bare"],
)
def test_one_shipped_parcel_without_a_tracking_number_keeps_the_handoff_offer(
    parts: dict[str, str | None],
) -> None:
    reply = shipped(**parts)
    assert reply.endswith(OFFER)
    assert reply.count(OFFER) == 1


def test_the_offer_for_a_missing_tracking_number_is_named_in_the_data_by_that_condition() -> None:
    assert PHRASES.parcels.closing_when_one["FULFILLED"] == ("handoff_offer",)
    assert "FULFILLED" not in PHRASES.parcels.closing_when
