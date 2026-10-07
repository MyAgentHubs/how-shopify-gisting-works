import json
from typing import Any

import pytest
from eval_support import BASE_SHIPMENT, found_result, grader, verdict_of

from gisting.eval.case import FINAL
from gisting.eval.style import sentence_list, word_count
from gisting.prompt.phrases import load_phrases
from gisting.prompt.replies import fixed_reply

PHRASES = load_phrases()
S = PHRASES.sentences
OFFER, THANKS, HAPPY = S["handoff_offer"], S["thanks_patience"], S["happy_to_help"]
PRIORITY = S["reminder_offer"]
CARRIER = "Test Parcel"
TRACKING = "TP-5257262993"
VALUES = {
    "<carrier>": CARRIER,
    "<tracking number>": TRACKING,
    "<month name and day, like March 9>": "October 5",
}
SCENARIOS = {
    ("transport_status", "FULFILLED"): "FULFILLED_NO_TRACKING",
    ("transport_status", "IN_TRANSIT"): "IN_TRANSIT",
    ("transport_status", "OUT_FOR_DELIVERY"): "OUT_FOR_DELIVERY",
    ("transport_status", "DELAYED"): "DELAYED",
    ("transport_status", "ATTEMPTED_DELIVERY"): "ATTEMPTED_DELIVERY",
    ("transport_status", "DELIVERED"): "DELIVERED",
    ("fulfillment_status", "UNFULFILLED"): "UNFULFILLED",
    ("fulfillment_status", "PARTIALLY_FULFILLED"): "PARTIALLY_FULFILLED",
}


def spec(scenario: str, **overrides: str | None) -> dict[str, Any]:
    return {
        "kind": "second",
        "category": "found",
        "scenario": scenario,
        "result": {"found": scenario, **overrides},
    }


def reply_from(table: str, status: str) -> str:
    template = PHRASES.reply_by_status[table][status]
    words = getattr(PHRASES, table)[status]
    text = template.format(words=words, **S)
    for placeholder, value in VALUES.items():
        text = text.replace(placeholder, value)
    return text


def problems(scenario: str, output: str, **overrides: str | None) -> tuple[str, ...]:
    return verdict_of(spec(scenario, **overrides), output).problems


PARTLY = ("fulfillment_status", "PARTIALLY_FULFILLED")


@pytest.mark.parametrize(("table", "status"), [key for key in SCENARIOS if key != PARTLY])
def test_every_reply_line_in_the_data_passes_the_grader_once_its_slots_are_filled(
    table: str, status: str
) -> None:
    scenario = SCENARIOS[table, status]
    verdict = verdict_of(spec(scenario), reply_from(table, status))
    assert verdict.ok, verdict.problems


def test_the_partly_shipped_line_as_the_renderer_writes_it_passes_the_grader() -> None:
    reply = fixed_reply(PHRASES, found_result("PARTIALLY_FULFILLED"))
    assert reply.startswith("Your order has partly shipped. First parcel is on its way: ")
    verdict = verdict_of(spec("PARTIALLY_FULFILLED"), reply)
    assert verdict.ok, verdict.problems


def test_the_fixed_sentences_are_not_leaks_or_facts_even_when_they_name_tracking_or_a_carrier() -> (
    None
):
    answer = reply_from("transport_status", "FULFILLED")
    assert "carrier" in answer
    assert verdict_of(spec("FULFILLED_NO_TRACKING"), answer).ok


NO_TRACKING_BASE = "Your order has shipped."
NO_TRACKING_SENTENCE = S["no_shipment_details"]
SPLIT_FORM = (
    "I do not have a tracking number or a delivery date yet. "
    "Tracking details usually appear once the carrier picks up and scans the parcel."
)


def test_a_reply_without_a_way_to_a_person_is_flagged_for_the_statuses_that_need_one() -> None:
    plain = f"{NO_TRACKING_BASE} {NO_TRACKING_SENTENCE}"
    assert "missing_handoff_offer" in problems("FULFILLED_NO_TRACKING", plain)
    delayed = (
        f"Your order is delayed. It is with {CARRIER}, tracking number {TRACKING}. "
        "Expected delivery: October 5."
    )
    assert "missing_handoff_offer" in problems("DELAYED", delayed)
    assert problems("DELAYED", f"{delayed} {OFFER}") == ()


def test_the_offer_is_still_unwanted_where_nothing_went_wrong() -> None:
    answer = reply_from("transport_status", "IN_TRANSIT") + f" {OFFER}"
    assert "unneeded_handoff_offer" in problems("IN_TRANSIT", answer)


def test_the_no_tracking_sentence_joins_the_missing_facts_and_the_reassurance_with_but() -> None:
    assert ", but tracking usually appears" in NO_TRACKING_SENTENCE
    answer = f"{NO_TRACKING_BASE} {NO_TRACKING_SENTENCE} {OFFER}"
    assert problems("FULFILLED_NO_TRACKING", answer) == ()


def test_the_old_two_sentence_form_without_a_but_is_no_longer_accepted() -> None:
    answer = f"{NO_TRACKING_BASE} {SPLIT_FORM} {OFFER}"
    assert "missing_reassurance" in problems("FULFILLED_NO_TRACKING", answer)


def test_a_reworded_reassurance_is_flagged_when_there_is_no_tracking() -> None:
    reworded = (
        f"{NO_TRACKING_BASE} I do not have a tracking number or a delivery date yet, "
        f"but the carrier adds them later. {OFFER}"
    )
    assert "missing_reassurance" in problems("FULFILLED_NO_TRACKING", reworded)


@pytest.mark.parametrize(
    "reason",
    [
        "It is waiting for the carrier to pick it up.",
        "The parcel has not been picked up yet.",
        "It is still at our warehouse.",
        "The carrier has not scanned it yet.",
    ],
)
def test_a_made_up_reason_for_the_missing_tracking_is_flagged(reason: str) -> None:
    answer = f"{NO_TRACKING_BASE} {NO_TRACKING_SENTENCE} {reason} {OFFER}"
    assert any(p.startswith("invented_reason") for p in problems("FULFILLED_NO_TRACKING", answer))


def test_an_unshipped_order_must_offer_to_send_the_team_a_reminder() -> None:
    blunt = "Your order has not shipped yet."
    assert "missing_reminder_offer" in problems("UNFULFILLED", blunt)
    assert problems("UNFULFILLED", reply_from("fulfillment_status", "UNFULFILLED")) == ()
    opener = f"{HAPPY} " + reply_from("fulfillment_status", "UNFULFILLED")
    assert problems("UNFULFILLED", opener) == ()


def test_an_unshipped_order_does_not_get_thanks_for_patience_or_a_human_offer() -> None:
    line = reply_from("fulfillment_status", "UNFULFILLED")
    assert "unneeded_thanks" in problems("UNFULFILLED", f"{line} {THANKS}")
    swapped = "Your order has not shipped yet, so I do not have a delivery date. " + OFFER
    found = problems("UNFULFILLED", swapped)
    assert "missing_reminder_offer" in found
    assert "unneeded_handoff_offer" in found


def test_the_reminder_offer_is_unwanted_where_the_order_has_shipped() -> None:
    answer = reply_from("transport_status", "IN_TRANSIT") + f" {PRIORITY}"
    assert "unneeded_reminder_offer" in problems("IN_TRANSIT", answer)


def test_the_friendly_sentences_do_not_count_toward_the_sentence_limit_or_the_first_sentence() -> (
    None
):
    answer = (
        f"{HAPPY} Your order is on its way. It is with {CARRIER}, tracking number {TRACKING}. "
        f"Expected delivery: October 5. {THANKS}"
    )
    assert problems("IN_TRANSIT", answer) == ()
    four = (
        "Your order is on its way. It is with Test Parcel. Tracking number TP-5257262993. "
        "Expected delivery: October 5. It is on time."
    )
    assert any(p.startswith("too_many_sentences") for p in problems("IN_TRANSIT", four))


def test_a_friendly_sentence_said_twice_is_a_repeat() -> None:
    answer = f"Your order is on its way. {THANKS} {THANKS}"
    assert "repeated_sentence" in problems("IN_TRANSIT", answer)


def test_an_unapproved_friendly_sentence_is_ordinary_content_and_counts() -> None:
    answer = (
        "Your order is on its way. It is with Test Parcel. Tracking number TP-5257262993. "
        "Expected delivery: October 5. Let me know if you need anything else!"
    )
    assert any(p.startswith("too_many_sentences") for p in problems("IN_TRANSIT", answer))


CONTROL_ONE = (
    "Your order has been fulfilled. It is with Test Parcel, tracking number TP-5257262993. "
    "Expected delivery: October 5. A delivery attempt was unsuccessful. "
    "I can hand you over to a human agent if you like."
)
CONTROL_TWO = (
    "Your order has been fulfilled. It is with Test Parcel, tracking number TP-5257262993. "
    "A delivery attempt was unsuccessful. It is expected to be delivered on October 5. "
    "I can hand you over to a human agent if you like."
)


@pytest.mark.parametrize(
    "answer", [CONTROL_ONE, CONTROL_TWO], ids=["status_fourth", "status_third"]
)
def test_a_failed_delivery_may_state_the_status_after_the_facts(answer: str) -> None:
    assert problems("ATTEMPTED_DELIVERY", answer) == ()


def test_a_failed_delivery_or_a_delay_still_has_to_say_so_somewhere() -> None:
    answer = (
        f"Your order has been fulfilled. It is with {CARRIER}, tracking number {TRACKING}. "
        f"Expected delivery: October 5. {OFFER}"
    )
    assert "reply_lacks_status" in problems("ATTEMPTED_DELIVERY", answer)
    assert "reply_lacks_status" in problems("DELAYED", answer)
    assert "first_sentence_lacks_status" not in problems("DELAYED", answer)


def test_every_other_status_still_needs_it_in_the_first_sentence() -> None:
    answer = f"It is with {CARRIER}, tracking number {TRACKING}. Your order is on its way."
    assert "first_sentence_lacks_status" in problems("IN_TRANSIT", answer)


def test_a_partly_shipped_order_has_to_say_that_the_rest_has_not_shipped() -> None:
    answer = (
        f"Your order has partly shipped. First parcel is on its way: it is with {CARRIER}, "
        f"tracking number {TRACKING}, expected delivery October 5."
    )
    assert "missing_unshipped_part" in problems("PARTIALLY_FULFILLED", answer)
    assert problems("PARTIALLY_FULFILLED", f"{answer} {S['unshipped_rest']}") == ()


def test_the_rest_of_a_partly_shipped_order_needs_its_missing_date_said_too() -> None:
    answer = (
        f"Your order has partly shipped. First parcel is on its way: it is with {CARRIER}, "
        f"tracking number {TRACKING}, expected delivery October 5. "
        "The rest of your items have not shipped yet."
    )
    assert "missing_no_details:rest_date" in problems("PARTIALLY_FULFILLED", answer)


def two_parcels() -> dict[str, Any]:
    wire = json.loads(json.dumps(found_result("PARTIALLY_FULFILLED")))
    later = {**BASE_SHIPMENT, "tracking_number": "TP-1111111111"}
    later["estimated_delivery"] = "2026-10-08T10:00:00Z"
    wire["order"]["shipments"].append({
        k: {"value": v, "source": "simulated"} for k, v in later.items()
    })
    return {
        "kind": "second",
        "category": "found",
        "scenario": "PARTIALLY_FULFILLED",
        "result": {"raw": wire},
    }


def test_every_shipment_of_a_partly_shipped_order_gets_its_own_date() -> None:
    both = (
        "First parcel is on its way: it is with Test Parcel, tracking number "
        "TP-5257262993, expected delivery October 5. Second parcel is on its way: "
        f"it is with Test Parcel, tracking number TP-1111111111, expected delivery October 8. "
        f"{S['unshipped_rest']}"
    )
    assert verdict_of(two_parcels(), both).ok, verdict_of(two_parcels(), both).problems
    only_one = both.replace(", expected delivery October 8", "")
    assert "missing_fact:estimated_date" in verdict_of(two_parcels(), only_one).problems


@pytest.mark.parametrize(
    ("status", "sentence", "key", "value", "placeholder"),
    [
        ("handed_off", "handoff_confirmation", "ticket", "HO-04837291", "<ticket>"),
        ("requested", "reminder_confirmation", "reference", "SR-04837291", "<reference>"),
    ],
)
def test_a_confirmation_with_the_reference_from_the_result_is_accepted_and_others_are_not(
    status: str, sentence: str, key: str, value: str, placeholder: str
) -> None:
    case = {
        "kind": "second",
        "category": status,
        "scenario": status,
        "result": {"raw": {"status": status, key: value}},
    }
    good = S[sentence].replace(placeholder, value)
    assert verdict_of(case, good).ok, verdict_of(case, good).problems
    missing = verdict_of(case, good.replace(value, "soon"))
    assert "missing_fact:reference" in missing.problems
    invented = verdict_of(case, good.replace(value, value[:3] + "99999999")).problems
    assert any(p.startswith("tracking:") for p in invented)


@pytest.mark.parametrize("status", ["unavailable", "locked"])
def test_a_failure_reply_without_the_offer_of_a_person_is_flagged(status: str) -> None:
    case = {"kind": "second", "category": status, "result": status}
    lines = {
        "unavailable": (
            "Sorry, order lookup is not available right now. Please try again in a little while."
        ),
        "locked": "Order lookups are locked for this chat after too many unsuccessful attempts.",
    }
    assert "missing_handoff_offer" in verdict_of(case, lines[status]).problems
    assert verdict_of(case, f"{lines[status]} {OFFER}").ok


def test_an_ask_without_its_example_is_named_as_such_and_the_full_ask_passes() -> None:
    case = {"category": "order_no_number", "user": "When will my package arrive?"}
    bare = PHRASES.ask_bare["both"]
    assert verdict_of(case, PHRASES.ask["both"], FINAL).ok
    assert verdict_of(case, bare, FINAL).problems == ("ask_lacks_example",)


def test_an_ask_with_the_wrong_example_is_not_a_fixed_sentence() -> None:
    case = {"category": "order_no_number", "user": "When will my package arrive?"}
    wrong = PHRASES.ask["both"].replace("#1234", "#1042")
    assert "ask_not_a_fixed_sentence" in verdict_of(case, wrong, FINAL).problems


def test_a_found_answer_never_says_prioritize_or_priority() -> None:
    for word in ("prioritize", "prioritise", "priority"):
        answer = f"{reply_from('transport_status', 'IN_TRANSIT')} We {word} it."
        assert f"forbidden_word:{word}" in problems("IN_TRANSIT", answer)


def test_no_fixed_sentence_or_reply_line_in_the_data_says_prioritize_or_priority() -> None:
    texts = [*PHRASES.sentences.values(), *PHRASES.ask.values(), *PHRASES.failure_replies.values()]
    texts += [t for table in PHRASES.reply_by_status.values() for t in table.values()]
    assert not [t for t in texts if "priorit" in t.lower()]


def test_every_fixed_sentence_stays_within_the_word_limit_of_the_style_decision() -> None:
    limit = grader().style.max_words_per_sentence
    texts = [*PHRASES.sentences.values(), *PHRASES.ask.values(), *PHRASES.failure_replies.values()]
    texts += [t for table in PHRASES.reply_by_status.values() for t in table.values()]
    for text in texts:
        for part in sentence_list(text, grader()):
            assert word_count(part) <= limit, part
