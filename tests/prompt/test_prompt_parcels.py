import itertools
import json
from typing import Any

import pytest
from replies_support import found, shipment

from gisting.prompt.phrases import PHRASES_FILE, PhrasesError, load_phrases, parse_phrases
from gisting.prompt.replies import fixed_reply

PHRASES = load_phrases()
S = PHRASES.sentences
OFFER, THANKS, REST = S["handoff_offer"], S["thanks_patience"], S["unshipped_rest"]
SEVERAL = (
    f"Your order was sent in several parcels, so the details are too long to list here. {OFFER}"
)
LATER = "2026-10-08T10:00:00Z"
TRANSPORT = ("FULFILLED", "IN_TRANSIT", "OUT_FOR_DELIVERY", "DELAYED", "ATTEMPTED_DELIVERY")
EXPECTED = {
    "IN_TRANSIT": (
        "{n} parcel is on its way: it is with Test Parcel, tracking number TP-{t}, "
        "expected delivery October {d}."
    ),
    "OUT_FOR_DELIVERY": (
        "{n} parcel is out for delivery: it is with Test Parcel, tracking number TP-{t}, "
        "expected delivery October {d}."
    ),
    "DELAYED": (
        "{n} parcel is delayed: it is with Test Parcel, tracking number TP-{t}, "
        "expected delivery October {d}."
    ),
    "ATTEMPTED_DELIVERY": (
        "{n} parcel had an unsuccessful delivery attempt: it is with Test Parcel, "
        "tracking number TP-{t}, expected delivery October {d}."
    ),
    "DELIVERED": (
        "{n} parcel has been delivered: it was sent with Test Parcel, "
        "tracking number TP-{t}, delivered on October {d}."
    ),
    "FULFILLED": (
        "{n} parcel has shipped, but I do not have a tracking number or a delivery date for it yet."
    ),
}


def parcel(status: str, number: int) -> dict[str, Any]:
    if status == "FULFILLED":
        return shipment(status, None, None)
    if status == "DELIVERED":
        return shipment(status, f"TP-{number}", None, f"2026-10-0{number}T10:00:00Z")
    return shipment(status, f"TP-{number}", f"2026-10-0{number}T10:00:00Z")


def line(status: str, index: int) -> str:
    names = ("First", "Second", "Third")
    return EXPECTED[status].format(n=names[index], t=index + 1, d=index + 1)


@pytest.mark.parametrize("status", list(EXPECTED))
def test_each_parcel_line_starts_with_that_parcels_own_status(status: str) -> None:
    other = "DELAYED" if status != "DELAYED" else "IN_TRANSIT"
    text = fixed_reply(PHRASES, found("FULFILLED", parcel(status, 1), parcel(other, 2)))
    assert text.startswith(line(status, 0))
    assert line(other, 1) in text


def test_a_delivered_parcel_followed_by_a_delayed_one_names_both_and_ends_with_the_offer() -> None:
    delivered = shipment("DELIVERED", "TP-1", None, "2026-10-03T10:00:00Z")
    delayed = shipment("DELAYED", "TP-2", LATER)
    text = fixed_reply(PHRASES, found("FULFILLED", delivered, delayed))
    assert text == (
        "First parcel has been delivered: it was sent with Test Parcel, tracking number TP-1, "
        "delivered on October 3. "
        "Second parcel is delayed: it is with Test Parcel, tracking number TP-2, "
        f"expected delivery October 8. {THANKS} {OFFER}"
    )


def test_three_parcels_on_their_way_have_no_opening_summary_and_no_closing() -> None:
    parcels = [parcel("IN_TRANSIT", n) for n in (1, 2, 3)]
    text = fixed_reply(PHRASES, found("FULFILLED", *parcels))
    assert text == " ".join(line("IN_TRANSIT", i) for i in range(3))


def test_a_delayed_parcel_among_others_adds_the_thanks_and_the_offer_once() -> None:
    parcels = [parcel("DELAYED", 1), parcel("DELAYED", 2)]
    text = fixed_reply(PHRASES, found("FULFILLED", *parcels))
    assert text.endswith(f"{THANKS} {OFFER}")
    assert text.count(THANKS) == 1 and text.count(OFFER) == 1


def test_a_failed_attempt_adds_only_the_offer_and_a_delay_adds_the_thanks_as_well() -> None:
    attempted = fixed_reply(
        PHRASES, found("FULFILLED", parcel("ATTEMPTED_DELIVERY", 1), parcel("IN_TRANSIT", 2))
    )
    assert attempted.endswith(f" {OFFER}") and THANKS not in attempted
    both = fixed_reply(
        PHRASES, found("FULFILLED", parcel("ATTEMPTED_DELIVERY", 1), parcel("DELAYED", 2))
    )
    assert both.endswith(f"{THANKS} {OFFER}") and both.count(OFFER) == 1


def test_a_partly_shipped_order_with_two_parcels_ends_with_the_note_on_the_rest() -> None:
    parcels = [parcel("IN_TRANSIT", 1), parcel("IN_TRANSIT", 2)]
    text = fixed_reply(PHRASES, found("PARTIALLY_FULFILLED", *parcels))
    assert text == f"{line('IN_TRANSIT', 0)} {line('IN_TRANSIT', 1)} {REST}"


def test_four_parcels_get_the_several_parcels_reply() -> None:
    parcels = [parcel("IN_TRANSIT", n) for n in (1, 2, 3, 4)]
    assert fixed_reply(PHRASES, found("FULFILLED", *parcels)) == SEVERAL


def test_three_delayed_parcels_still_fit_the_five_sentences_of_a_delayed_order() -> None:
    parcels = [parcel("DELAYED", n) for n in (1, 2, 3)]
    text = fixed_reply(PHRASES, found("FULFILLED", *parcels))
    assert text.count("parcel is delayed") == 3 and text.endswith(f"{THANKS} {OFFER}")


def test_more_sentences_than_the_limit_of_the_order_gets_the_several_parcels_reply() -> None:
    parcels = [parcel("DELAYED", 1), parcel("IN_TRANSIT", 2), parcel("IN_TRANSIT", 3)]
    assert fixed_reply(PHRASES, found("PARTIALLY_FULFILLED", *parcels)) == SEVERAL


def test_three_parcels_on_their_way_with_a_part_not_shipped_stay_within_four_sentences() -> None:
    parcels = [parcel("IN_TRANSIT", n) for n in (1, 2, 3)]
    text = fixed_reply(PHRASES, found("PARTIALLY_FULFILLED", *parcels))
    assert text.endswith(REST) and "several parcels" not in text


def test_the_several_parcels_reply_carries_the_approved_handoff_offer_word_for_word() -> None:
    assert PHRASES.parcels.many_reply == SEVERAL
    assert SEVERAL.endswith("Would you like me to connect you with a member of our team?")


def test_the_limits_are_read_from_the_data() -> None:
    limits = PHRASES.limits
    assert limits.max_parcels == 3
    assert limits.sentence_limit(["IN_TRANSIT"]) == 4
    assert limits.sentence_limit(["DELAYED", "IN_TRANSIT"]) == 5


def test_a_parcel_missing_the_date_says_so_and_never_shows_a_slot() -> None:
    partial = shipment("IN_TRANSIT", "TP-2", None)
    text = fixed_reply(PHRASES, found("FULFILLED", parcel("IN_TRANSIT", 1), partial))
    assert text == (
        f"{line('IN_TRANSIT', 0)} Second parcel is on its way: it is with Test Parcel, "
        "tracking number TP-2, but I do not have a delivery date for it yet."
    )


def with_missing(node: dict[str, Any], missing: tuple[str, ...]) -> dict[str, Any]:
    kept = dict(node)
    for key in missing:
        kept[key] = {"value": None, "source": "shopify"}
    return kept


COMBOS = [
    combo
    for size in range(4)
    for combo in itertools.combinations(("carrier", "tracking_number", "date"), size)
]


def blank(node: dict[str, Any], combo: tuple[str, ...]) -> dict[str, Any]:
    keys = {
        "date": "delivered_at"
        if node["transport_status"]["value"] == "DELIVERED"
        else "estimated_delivery"
    }
    return with_missing(node, tuple(keys.get(item, item) for item in combo))


@pytest.mark.parametrize("combo", COMBOS)
@pytest.mark.parametrize("status", [*TRANSPORT, "DELIVERED"])
def test_a_single_parcel_never_shows_an_unfilled_slot(status: str, combo: tuple[str, ...]) -> None:
    node = blank(parcel(status, 1), combo)
    text = fixed_reply(PHRASES, found("FULFILLED", node))
    assert "<" not in text and ">" not in text


@pytest.mark.parametrize("combo", COMBOS)
@pytest.mark.parametrize("status", [*TRANSPORT, "DELIVERED"])
def test_several_parcels_never_show_an_unfilled_slot(status: str, combo: tuple[str, ...]) -> None:
    node = blank(parcel(status, 1), combo)
    for fulfillment in ("FULFILLED", "PARTIALLY_FULFILLED"):
        text = fixed_reply(PHRASES, found(fulfillment, node, parcel("IN_TRANSIT", 2)))
        assert "<" not in text and ">" not in text


@pytest.mark.parametrize("combo", COMBOS)
def test_a_partly_shipped_single_parcel_never_shows_an_unfilled_slot(
    combo: tuple[str, ...],
) -> None:
    node = blank(parcel("IN_TRANSIT", 1), combo)
    text = fixed_reply(PHRASES, found("PARTIALLY_FULFILLED", node))
    assert "<" not in text and ">" not in text


def test_a_single_parcel_without_a_tracking_number_and_a_date_keeps_its_status() -> None:
    node = shipment("IN_TRANSIT", None, None)
    text = fixed_reply(PHRASES, found("FULFILLED", node))
    assert text == (
        "Your order is on its way, but I do not have a tracking number or a delivery date yet."
    )


def test_a_single_parcel_missing_only_the_date_says_so_without_the_tracking_reassurance() -> None:
    node = shipment("IN_TRANSIT", "TP-1", None)
    text = fixed_reply(PHRASES, found("FULFILLED", node))
    assert text == (
        "Your order is on its way: it is with Test Parcel, tracking number TP-1, "
        "but I do not have a delivery date yet."
    )


def test_a_delayed_single_parcel_without_details_keeps_the_delay_and_the_closing() -> None:
    text = fixed_reply(PHRASES, found("FULFILLED", shipment("DELAYED", None, None)))
    assert text == (
        "Your order is delayed, but I do not have a tracking number or a delivery date yet. "
        f"{THANKS} {OFFER}"
    )


def test_a_partly_shipped_single_parcel_without_details_keeps_its_status() -> None:
    text = fixed_reply(PHRASES, found("PARTIALLY_FULFILLED", shipment("IN_TRANSIT", None, None)))
    assert text == (
        "Your order has partly shipped. First parcel is on its way, but I do not have a "
        f"tracking number or a delivery date for it yet. {REST}"
    )


def document() -> dict[str, Any]:
    return json.loads(PHRASES_FILE.read_text(encoding="utf-8"))


def changed(edits: dict[str, Any]) -> str:
    return json.dumps({**document(), **edits})


def without_key(name: str, key: str) -> dict[str, Any]:
    kept = dict(document()[name])
    del kept[key]
    return kept


def with_key(name: str, key: str, value: object) -> dict[str, Any]:
    return {**document()[name], key: value}


MALFORMED_COPY: list[dict[str, Any]] = [
    {"parcel_status": without_key("parcel_status", "DELAYED")},
    {"parcel_status": with_key("parcel_status", "UNKNOWN", "is lost")},
    {"parcel_status": with_key("parcel_status", "DELAYED", " ")},
    {"parcel_facts": without_key("parcel_facts", "delivered")},
    {"parcel_facts": with_key("parcel_facts", "shipped", {"carrier": "it is with {value}"})},
    {
        "parcel_facts": with_key(
            "parcel_facts",
            "shipped",
            {**document()["parcel_facts"]["shipped"], "date": "expected delivery soon"},
        )
    },
    {"parcel_missing": without_key("parcel_missing", "both")},
    {"parcel_missing": with_key("parcel_missing", "date", "but I do not have a date yet")},
    {"parcel_forms": without_key("parcel_forms", "one")},
    {"parcel_forms": with_key("parcel_forms", "several", {"subject": "The parcel", "for_it": ""})},
    {"parcel_forms": with_key("parcel_forms", "one", {"subject": "Your order"})},
    {"ordinals": ["First"]},
    {"parcel_closing": {"order": ["handoff_offer"], "when": {"DELAYED": ["thanks_patience"]}}},
    {"parcel_closing": {"order": ["no_such_sentence"], "when": {}}},
    {
        "parcel_closing": {
            **document()["parcel_closing"],
            "also_without_tracking": {"FULFILLED": ["no_such_sentence"]},
        }
    },
    {"many_parcels_reply": "{no_such_sentence}"},
    {"many_parcels_reply": " "},
    {"limits": {**document()["limits"], "max_parcels": 0}},
    {"limits": {**document()["limits"], "max_parcels": 9}},
    {"limits": {**document()["limits"], "max_sentences": "four"}},
    {"limits": {"max_sentences": 4}},
    {"limits": without_key("limits", "several_parcels_from_by_line")},
    {"limits": {**document()["limits"], "several_parcels_from_by_line": {"DELAYED": 0}}},
]


@pytest.mark.parametrize("edits", MALFORMED_COPY)
def test_malformed_parcel_copy_is_rejected_when_the_phrases_load(edits: dict[str, Any]) -> None:
    with pytest.raises(PhrasesError):
        parse_phrases(changed(edits))


def test_a_reply_line_that_opens_with_a_slot_is_rejected() -> None:
    lines = document()["reply_by_status"]
    lines["transport_status"]["IN_TRANSIT"] = "<carrier> has it. Your order {words}."
    with pytest.raises(PhrasesError):
        parse_phrases(changed({"reply_by_status": lines}))
