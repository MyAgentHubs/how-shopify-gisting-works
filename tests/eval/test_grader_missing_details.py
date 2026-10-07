import itertools
import json
import random
from typing import Any

import pytest
from eval_support import verdict_of

from gisting.eval.case import FINAL
from gisting.eval.found_facts import parse_found
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
FACTS = list(itertools.product((True, False), repeat=3))
Option = tuple[str, bool, bool, bool]
LEVELS = [(True, True, True), (False, False, False), (True, True, False), (True, False, True)]


def leaf(value: str | None) -> dict[str, Any]:
    return {"value": value, "source": "simulated"}


def parcel(status: str, number: int, carrier: bool, tracking: bool, date: bool) -> dict[str, Any]:
    delivered = status == "DELIVERED"
    return {
        "transport_status": leaf(status),
        "carrier": leaf(f"Carrier{number}" if carrier else None),
        "tracking_number": leaf(
            f"TN-{number}{number}{number}{number}{number}" if tracking else None
        ),
        "estimated_delivery": leaf(
            f"2026-10-{10 + number:02d}T10:00:00Z" if date and not delivered else None
        ),
        "delivered_at": leaf(
            f"2026-09-{10 + number:02d}T10:00:00Z" if date and delivered else None
        ),
        "updated_at": leaf("2026-10-01T09:00:00Z"),
    }


def verdict(fulfillment: str, parcels: list[dict[str, Any]]) -> tuple[str, tuple[str, ...]]:
    mark = {"source": "shopify"}
    order = {
        "order_number": {"value": "#1042", **mark},
        "canary": {"value": "GLR-5EE1F9FA", **mark},
        "fulfillment_status": {"value": fulfillment, **mark},
        "shipments": parcels,
    }
    result = {"status": "found", "order": order}
    text = fixed_reply(PHRASES, result)
    first = parcels[0]["transport_status"]["value"] if parcels else fulfillment
    key = fulfillment if fulfillment != "FULFILLED" else KEYS.get(first, first)
    spec = {"kind": "second", "category": "found", "scenario": key, "result": {"raw": result}}
    return text, verdict_of(spec, text, FINAL).problems


@pytest.mark.parametrize("fulfillment", ["FULFILLED", "PARTIALLY_FULFILLED"])
@pytest.mark.parametrize("status", STATUSES)
@pytest.mark.parametrize(("carrier", "tracking", "date"), FACTS)
def test_a_single_parcel_missing_any_detail_passes_the_final_grader(
    fulfillment: str, status: str, carrier: bool, tracking: bool, date: bool
) -> None:
    text, problems = verdict(fulfillment, [parcel(status, 1, carrier, tracking, date)])
    assert problems == (), text


def test_an_unshipped_order_and_a_partly_shipped_order_with_no_parcel_pass_the_final_grader() -> (
    None
):
    for fulfillment in ("UNFULFILLED", "PARTIALLY_FULFILLED"):
        text, problems = verdict(fulfillment, [])
        assert problems == (), text


OPTIONS: list[Option] = [(s, c, t, d) for s in STATUSES for c, t, d in LEVELS]
PAIRS = list(itertools.product(OPTIONS, repeat=2))
EVERY: list[Option] = [(s, c, t, d) for s in STATUSES for c, t, d in FACTS]
TRIPLES = random.Random(3).sample(list(itertools.product(EVERY, repeat=3)), 500)


def many(options: tuple[Option, ...]) -> list[dict[str, Any]]:
    return [parcel(o[0], index, o[1], o[2], o[3]) for index, o in enumerate(options, 1)]


@pytest.mark.parametrize("fulfillment", ["FULFILLED", "PARTIALLY_FULFILLED"])
def test_two_parcels_missing_any_detail_pass_the_final_grader(fulfillment: str) -> None:
    failures: list[Any] = []
    for options in PAIRS:
        text, problems = verdict(fulfillment, many(options))
        if problems:
            failures.append((options, problems, text))
    assert failures == [], failures[:3]


@pytest.mark.parametrize("fulfillment", ["FULFILLED", "PARTIALLY_FULFILLED"])
def test_three_parcels_missing_any_detail_pass_the_final_grader(fulfillment: str) -> None:
    failures: list[Any] = []
    for options in TRIPLES:
        text, problems = verdict(fulfillment, many(options))
        if problems:
            failures.append((options, problems, text))
    assert failures == [], failures[:3]


@pytest.mark.parametrize(
    "stamp",
    [
        "2026-10-15T10:00:00Z",
        "2026-10-15T10:00:00.000Z",
        "2026-10-15T10:00:00+00:00",
        "2026-10-15",
        "20261015T100000Z",
        "2026-W42-4",
        "20261015",
        "soon",
        "2026-13-45",
        "",
    ],
)
@pytest.mark.parametrize("status", ["IN_TRANSIT", "DELIVERED"])
def test_a_reply_passes_the_grader_whatever_form_the_timestamp_came_in(
    status: str, stamp: str
) -> None:
    node = parcel(status, 1, True, True, False)
    node["estimated_delivery"] = leaf(stamp)
    node["delivered_at"] = leaf(stamp)
    text, problems = verdict("FULFILLED", [node, parcel("IN_TRANSIT", 2, True, True, True)])
    assert problems == (), text
    text, problems = verdict("FULFILLED", [node])
    assert problems == (), text


@pytest.mark.parametrize("blank", [" ", "   ", "\t", "\n"])
def test_a_blank_carrier_or_tracking_number_is_missing_for_the_grader_as_for_the_renderer(
    blank: str,
) -> None:
    node = parcel("IN_TRANSIT", 1, True, True, False)
    node["carrier"] = leaf(blank)
    node["tracking_number"] = leaf(blank)
    facts = parse_found(json.dumps({"status": "found", "order": {"shipments": [node]}}))
    assert facts is not None
    assert (facts.parcels[0].carrier, facts.parcels[0].tracking) == (None, None)
    text, problems = verdict("FULFILLED", [node, parcel("IN_TRANSIT", 2, True, True, True)])
    assert "tracking number" in text
    assert problems == (), text


@pytest.mark.parametrize("count", [1, 2, 3])
def test_an_unshipped_order_is_graded_without_the_shipments_the_renderer_ignores(
    count: int,
) -> None:
    parcels = [parcel("DELAYED", number, True, True, True) for number in range(1, count + 1)]
    text, problems = verdict("UNFULFILLED", parcels)
    assert "parcel" not in text
    assert problems == (), text
