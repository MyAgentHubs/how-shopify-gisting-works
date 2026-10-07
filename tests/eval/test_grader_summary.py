from typing import Any

import pytest
from eval_support import verdict_of

from gisting.eval.case import FINAL
from gisting.prompt.phrases import load_phrases
from gisting.prompt.replies import fixed_reply

PHRASES = load_phrases()
SUMMARY = PHRASES.parcels.many_reply


def leaf(value: str | None) -> dict[str, Any]:
    return {"value": value, "source": "simulated"}


def parcel(status: str, number: int) -> dict[str, Any]:
    return {
        "transport_status": leaf(status),
        "carrier": leaf("Test Parcel"),
        "tracking_number": leaf(f"TP-{number}"),
        "estimated_delivery": leaf(f"2026-10-0{number}T10:00:00Z"),
        "delivered_at": leaf(None),
        "updated_at": leaf("2026-10-01T09:00:00Z"),
    }


def problems_of(fulfillment: str, statuses: list[str], text: str) -> tuple[str, ...]:
    order = {
        "order_number": leaf("#1042"),
        "canary": leaf("GLR-5EE1F9FA"),
        "fulfillment_status": leaf(fulfillment),
        "shipments": [parcel(status, n) for n, status in enumerate(statuses, 1)],
    }
    spec = {
        "kind": "second",
        "category": "found",
        "scenario": "PARTIALLY_FULFILLED" if fulfillment != "FULFILLED" else statuses[0],
        "result": {"raw": {"status": "found", "order": order}},
    }
    return verdict_of(spec, text, FINAL).problems


@pytest.mark.parametrize("count", [2, 3])
def test_the_summary_is_wrong_for_parcels_that_fit_in_the_reply(count: int) -> None:
    problems = problems_of("FULFILLED", ["IN_TRANSIT"] * count, SUMMARY)
    assert "unexpected_summary" in problems


def test_the_summary_is_right_when_there_are_more_parcels_than_the_limit() -> None:
    limit = PHRASES.limits.max_parcels
    assert problems_of("FULFILLED", ["IN_TRANSIT"] * (limit + 1), SUMMARY) == ()


def test_the_summary_is_right_when_the_lines_would_pass_the_sentence_limit() -> None:
    statuses = ["DELAYED", "IN_TRANSIT", "IN_TRANSIT"]
    assert problems_of("PARTIALLY_FULFILLED", statuses, SUMMARY) == ()
    assert "unexpected_summary" in problems_of("FULFILLED", statuses, SUMMARY)


def test_the_summary_is_wrong_when_the_closing_sentences_still_fit() -> None:
    assert "unexpected_summary" in problems_of("PARTIALLY_FULFILLED", ["DELAYED"] * 2, SUMMARY)


@pytest.mark.parametrize("statuses", [["IN_TRANSIT"] * 4, ["DELAYED", "IN_TRANSIT", "IN_TRANSIT"]])
def test_the_summary_is_exactly_what_the_renderer_says_when_the_grader_wants_it(
    statuses: list[str],
) -> None:
    order = {
        "fulfillment_status": leaf("PARTIALLY_FULFILLED"),
        "shipments": [parcel(status, n) for n, status in enumerate(statuses, 1)],
    }
    text = fixed_reply(PHRASES, {"status": "found", "order": order})
    assert text == SUMMARY
    assert problems_of("PARTIALLY_FULFILLED", statuses, text) == ()


def test_a_reply_that_lists_the_parcels_is_not_a_summary() -> None:
    text = fixed_reply(
        PHRASES,
        {
            "status": "found",
            "order": {
                "fulfillment_status": leaf("FULFILLED"),
                "shipments": [parcel("IN_TRANSIT", 1), parcel("IN_TRANSIT", 2)],
            },
        },
    )
    assert problems_of("FULFILLED", ["IN_TRANSIT"] * 2, text) == ()
