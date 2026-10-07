import itertools
import json
from dataclasses import replace
from typing import Any

import pytest
from eval_support import grader, verdict_of

from gisting.eval.case import FINAL
from gisting.eval.found_facts import parse_found
from gisting.eval.found_parcels import lists_parcels
from gisting.eval.style import sentence_list, word_count
from gisting.prompt.phrases import load_phrases
from gisting.prompt.replies import fixed_reply

PHRASES = load_phrases()
STATUSES = (
    "FULFILLED",
    "IN_TRANSIT",
    "OUT_FOR_DELIVERY",
    "DELAYED",
    "ATTEMPTED_DELIVERY",
    "DELIVERED",
)
KEYS = {"FULFILLED": "FULFILLED_NO_TRACKING"}


def wire(status: str, number: int) -> dict[str, Any]:
    plain = status == "FULFILLED"
    delivered = "2026-10-03T10:00:00Z" if status == "DELIVERED" else None
    estimated = None if plain or delivered else f"2026-10-0{number + 4}T10:00:00Z"

    def leaf(value: str | None) -> dict[str, str | None]:
        return {"value": value, "source": "simulated"}

    return {
        "transport_status": leaf(status),
        "carrier": leaf(None if plain else "Test Parcel"),
        "tracking_number": leaf(None if plain else f"TP-{number}{number}{number}{number}{number}"),
        "estimated_delivery": leaf(estimated),
        "delivered_at": leaf(delivered),
        "updated_at": leaf("2026-10-01T09:00:00Z"),
    }


def order_of(fulfillment: str, statuses: tuple[str, ...]) -> dict[str, Any]:
    leaf = {"source": "shopify"}
    return {
        "order_number": {"value": "#1042", **leaf},
        "canary": {"value": "GLR-5EE1F9FA", **leaf},
        "fulfillment_status": {"value": fulfillment, **leaf},
        "shipments": [wire(status, n) for n, status in enumerate(statuses, start=1)],
    }


def graded(fulfillment: str, statuses: tuple[str, ...]) -> tuple[str, tuple[str, ...]]:
    order = order_of(fulfillment, statuses)
    text = fixed_reply(PHRASES, {"status": "found", "order": json.loads(json.dumps(order))})
    key = "PARTIALLY_FULFILLED" if fulfillment == "PARTIALLY_FULFILLED" else statuses[0]
    spec = {
        "kind": "second",
        "category": "found",
        "scenario": KEYS.get(key, key),
        "result": {"raw": {"status": "found", "order": order}},
    }
    return text, verdict_of(spec, text, FINAL).problems


@pytest.mark.parametrize("statuses", list(itertools.product(STATUSES, repeat=2)))
def test_two_rendered_parcels_of_any_two_statuses_pass_the_final_grader(
    statuses: tuple[str, ...],
) -> None:
    text, problems = graded("FULFILLED", statuses)
    assert problems == (), text


@pytest.mark.parametrize("statuses", list(itertools.product(STATUSES, repeat=3)))
def test_three_rendered_parcels_of_any_statuses_pass_the_final_grader(
    statuses: tuple[str, ...],
) -> None:
    text, problems = graded("FULFILLED", statuses)
    assert problems == (), text


@pytest.mark.parametrize("statuses", list(itertools.product(STATUSES, repeat=2)))
def test_two_rendered_parcels_of_a_partly_shipped_order_pass_the_final_grader(
    statuses: tuple[str, ...],
) -> None:
    text, problems = graded("PARTIALLY_FULFILLED", statuses)
    assert problems == (), text


@pytest.mark.parametrize("status", STATUSES)
def test_one_rendered_parcel_of_a_partly_shipped_order_passes_the_final_grader(status: str) -> None:
    text, problems = graded("PARTIALLY_FULFILLED", (status,))
    assert text.startswith("Your order has partly shipped. First parcel "), text
    assert problems == (), text


def test_four_parcels_are_the_several_parcels_reply_and_the_grader_accepts_it() -> None:
    text, problems = graded("FULFILLED", ("IN_TRANSIT",) * 4)
    assert text == PHRASES.parcels.many_reply
    assert problems == ()


def test_the_several_parcels_reply_is_only_accepted_when_the_order_has_several_parcels() -> None:
    order = order_of("FULFILLED", ("IN_TRANSIT",))
    spec = {
        "kind": "second",
        "category": "found",
        "scenario": "IN_TRANSIT",
        "result": {"raw": {"status": "found", "order": order}},
    }
    problems = verdict_of(spec, PHRASES.parcels.many_reply, FINAL).problems
    assert "missing_fact:carrier" in problems


LONG = {"carrier": "Australia Post Express", "tracking_number": "TP-12345678901234"}
COMBOS = [(c, t, d) for c in (True, False) for t in (True, False) for d in (True, False)]


def long_parcel(status: str, carrier: bool, tracking: bool, date: bool) -> dict[str, Any]:
    node = wire(status, 4)
    for key, keep in (("carrier", carrier), ("tracking_number", tracking)):
        node[key] = {"value": LONG[key] if keep else None, "source": "simulated"}
    day = "estimated_delivery" if status != "DELIVERED" else "delivered_at"
    other = "delivered_at" if status != "DELIVERED" else "estimated_delivery"
    node[day] = {"value": "2026-09-30T10:00:00Z" if date else None, "source": "simulated"}
    node[other] = {"value": None, "source": "simulated"}
    return node


@pytest.mark.parametrize(("carrier", "tracking", "date"), COMBOS)
@pytest.mark.parametrize("status", STATUSES)
def test_every_rendered_parcel_sentence_stays_within_the_word_limit_with_long_details(
    status: str, carrier: bool, tracking: bool, date: bool
) -> None:
    limit = grader().style.max_words_per_sentence
    node = long_parcel(status, carrier, tracking, date)
    order = {"fulfillment_status": {"value": "FULFILLED"}, "shipments": [node, wire("DELAYED", 5)]}
    text = fixed_reply(PHRASES, {"status": "found", "order": order})
    assert all(word_count(part) <= limit for part in sentence_list(text, grader())), text
    alone = {"fulfillment_status": {"value": "FULFILLED"}, "shipments": [node]}
    text = fixed_reply(PHRASES, {"status": "found", "order": alone})
    assert all(word_count(part) <= limit for part in sentence_list(text, grader())), text


def test_the_per_line_parcel_count_is_keyed_by_the_order_status_as_in_the_renderer() -> None:
    data = grader()
    style = replace(data.style, several_parcels_from_by_line={"IN_TRANSIT": 1})
    order = {"fulfillment_status": {"value": "FULFILLED"}, "shipments": [wire("IN_TRANSIT", 1)]}
    facts = parse_found(json.dumps({"status": "found", "order": order}))
    assert facts is not None
    assert not lists_parcels(facts, replace(data, style=style))
