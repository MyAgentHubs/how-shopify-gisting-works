from typing import Any

import pytest
from eval_support import grader, load_corpus, verdict_of

from gisting.eval.case import DECISION, FINAL, FIRST, RAW

BAD = [*load_corpus("known_bad.json"), *load_corpus("known_bad_policy.json")]
GOOD = [*load_corpus("known_good.json"), *load_corpus("known_good_policy.json")]
FIRST_CATEGORIES = (
    "order_full",
    "order_no_email",
    "order_no_number",
    "offtopic",
    "injection",
    "handoff_agree",
    "handoff_request",
    "handoff_decline",
    "reminder_agree",
    "reminder_decline",
    "policy_question",
    "policy_outside_kb",
)
SECOND_KEYS = (
    "IN_TRANSIT",
    "OUT_FOR_DELIVERY",
    "DELIVERED",
    "DELAYED",
    "ATTEMPTED_DELIVERY",
    "FULFILLED_NO_TRACKING",
    "UNFULFILLED",
    "PARTIALLY_FULFILLED",
    "no_match",
    "unavailable",
    "locked",
    "handed_off",
    "requested",
    "needs_customer_input",
)


def entry_id(entry: dict[str, Any]) -> str:
    return str(entry["id"])


def key_of(entry: dict[str, Any]) -> str:
    return str(entry.get("scenario") or entry["category"])


def layers_of(entry: dict[str, Any]) -> tuple[str, ...]:
    if "layers" in entry:
        return tuple(entry["layers"])
    return (RAW, FINAL, DECISION) if entry.get("kind", FIRST) == FIRST else (RAW, FINAL)


def layered(entries: list[dict[str, Any]]) -> list[Any]:
    chosen = [(entry, layer) for entry in entries for layer in layers_of(entry)]
    return [pytest.param(entry, layer, id=f"{entry_id(entry)}@{layer}") for entry, layer in chosen]


@pytest.mark.parametrize(("entry", "layer"), layered(BAD))
def test_a_known_bad_sample_is_flagged_for_its_reason(entry: dict[str, Any], layer: str) -> None:
    verdict = verdict_of(entry, layer=layer)
    assert not verdict.ok
    for expected in entry.get("problems") or [entry["problem"]]:
        assert any(problem.startswith(expected) for problem in verdict.problems), verdict.problems


@pytest.mark.parametrize(("entry", "layer"), layered(GOOD))
def test_a_known_good_sample_is_not_flagged(entry: dict[str, Any], layer: str) -> None:
    verdict = verdict_of(entry, layer=layer)
    assert verdict.ok, verdict.problems


def test_the_corpus_is_large_and_every_ids_is_unique() -> None:
    ids = [entry_id(entry) for entry in (*BAD, *GOOD)]
    assert len(set(ids)) == len(ids)
    assert len(BAD) >= 80
    assert len(GOOD) >= 40


@pytest.mark.parametrize("key", [*FIRST_CATEGORIES, *SECOND_KEYS])
def test_every_category_and_scenario_has_known_good_and_known_bad_samples(key: str) -> None:
    assert any(key_of(entry) == key or entry["category"] == key for entry in BAD)
    assert any(key_of(entry) == key or entry["category"] == key for entry in GOOD)


@pytest.mark.parametrize("key", FIRST_CATEGORIES)
def test_every_first_turn_category_has_decision_samples_both_ways(key: str) -> None:
    for entries in (BAD, GOOD):
        assert any(entry["category"] == key and DECISION in layers_of(entry) for entry in entries)


def test_every_scenario_the_grader_knows_is_in_the_corpus() -> None:
    known = set(grader().scenarios)
    assert known <= set(SECOND_KEYS)
    assert known <= {key_of(entry) for entry in GOOD}
