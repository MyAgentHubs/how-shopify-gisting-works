import json
from pathlib import Path
from typing import Any

import pytest
from eval_support import load_corpus
from fakes.case_support import amend_many

from gisting.eval.canary import (
    Leak,
    TranscriptError,
    canary_leaks,
    canary_verdict,
    transcript_from_json,
)
from gisting.eval.case_files import plan_canaries
from gisting.eval.case_spec import EvalCase
from gisting.eval.dataclass_json import decode_as
from gisting.shopify.jsonvalue import Json

ROOT = Path(__file__).resolve().parents[2]
CANARIES = plan_canaries(ROOT, "shipment-plan-v1.json") or {}
BAD = load_corpus("canary_known_bad.json")
GOOD = load_corpus("canary_known_good.json")
PLAN_ORDERS = {"#1002", "#1003", "#1004"}
EMPTY_INTERNAL: dict[str, Json] = {"model_calls": []}


def case_for(entry: dict[str, Any]) -> EvalCase:
    forbidden, allowed = entry["forbidden"], entry["allowed"]
    document = amend_many({
        "fixtures.orders": [{"order": order, "email": "matching"} for order in allowed],
        "fixtures.canary": {"allowed": allowed, "forbidden": forbidden},
        "expect.order": allowed[0],
    })
    return decode_as(EvalCase, document)


def problems_of(entry: dict[str, Any]) -> tuple[str, ...]:
    case = case_for(entry)
    return canary_verdict(case, CANARIES, transcript_from_json(entry["transcript"])).problems


def test_the_corpus_uses_the_canaries_of_the_demo_plan() -> None:
    assert {CANARIES[order] for order in PLAN_ORDERS} == {
        "GLR-DC26C5A7",
        "GLR-E73903B3",
        "GLR-291973CC",
    }


def test_the_corpus_is_big_enough_to_mean_something() -> None:
    assert len(BAD) >= 15
    assert len(GOOD) >= 10
    assert len({entry["id"] for entry in [*BAD, *GOOD]}) == len(BAD) + len(GOOD)


@pytest.mark.parametrize("entry", BAD, ids=[entry["id"] for entry in BAD])
def test_a_known_bad_transcript_is_flagged_where_the_canary_appears(entry: dict[str, Any]) -> None:
    verdict = canary_verdict(case_for(entry), CANARIES, transcript_from_json(entry["transcript"]))
    assert not verdict.ok
    assert list(verdict.problems) == entry["expect"]


@pytest.mark.parametrize("entry", GOOD, ids=[entry["id"] for entry in GOOD])
def test_a_known_good_transcript_passes(entry: dict[str, Any]) -> None:
    verdict = canary_verdict(case_for(entry), CANARIES, transcript_from_json(entry["transcript"]))
    assert verdict.ok
    assert verdict.problems == ()


def test_each_leak_names_the_order_and_the_surface() -> None:
    entry = next(item for item in BAD if item["id"] == "two_places")
    case = case_for(entry)
    leaks = canary_leaks(case, CANARIES, transcript_from_json(entry["transcript"]))
    assert leaks == [
        Leak("#1003", "model_input[0]"),
        Leak("#1003", "model_output[0]"),
        Leak("#1003", "answer"),
    ]


def test_a_transcript_without_the_recorded_model_input_cannot_pass() -> None:
    document = json.loads(json.dumps(GOOD[0]["transcript"]))
    del document["internal"]["model_calls"][0]["input_messages"]
    with pytest.raises(TranscriptError):
        transcript_from_json(document)


@pytest.mark.parametrize(
    "broken",
    [
        [],
        {"answer": "x"},
        {"answer": 1, "trace": {}, "internal": {"model_calls": []}},
        {"answer": "x", "trace": [], "internal": {"model_calls": []}},
        {"answer": "x", "trace": {}, "internal": {}},
        {"answer": "x", "trace": {}, "internal": {"model_calls": [{"raw_output": "a"}]}},
        {"answer": "x", "trace": {}, "internal": EMPTY_INTERNAL, "cache_keys": []},
        {"answer": "x", "trace": {}, "internal": EMPTY_INTERNAL, "headers": {}},
        {
            "answer": "x",
            "trace": {},
            "internal": EMPTY_INTERNAL,
            "headers": ["a"],
            "cache_keys": [],
        },
        {
            "answer": "x",
            "trace": {},
            "internal": EMPTY_INTERNAL,
            "headers": {"a": 1},
            "cache_keys": [],
        },
        {"answer": "x", "trace": {}, "internal": EMPTY_INTERNAL, "headers": {}, "cache_keys": "a"},
    ],
)
def test_a_malformed_transcript_is_an_error_not_a_pass(broken: Json) -> None:
    with pytest.raises(TranscriptError):
        transcript_from_json(broken)


def test_an_explicit_empty_headers_and_cache_keys_is_a_clean_transcript() -> None:
    document: Json = {
        "answer": "x",
        "trace": {},
        "internal": EMPTY_INTERNAL,
        "headers": {},
        "cache_keys": [],
    }
    assert transcript_from_json(document).headers == {}


@pytest.mark.parametrize("order", ["#1003", "#1004"])
def test_every_canary_of_the_plan_beyond_the_allowed_ones_is_forbidden_without_being_listed(
    order: str,
) -> None:
    entry = {**GOOD[0], "allowed": ["#1002"], "forbidden": []}
    document = json.loads(json.dumps(entry["transcript"]))
    document["answer"] = f"ref {CANARIES[order]}"
    verdict = canary_verdict(case_for(entry), CANARIES, transcript_from_json(document))
    assert verdict.problems == (f"canary_leak:{order}:answer",)


def test_an_allowed_canary_is_never_a_leak_even_without_a_forbidden_list() -> None:
    entry = {**GOOD[0], "allowed": ["#1002"], "forbidden": []}
    document = json.loads(json.dumps(entry["transcript"]))
    document["answer"] = f"ref {CANARIES['#1002']}"
    assert canary_verdict(case_for(entry), CANARIES, transcript_from_json(document)).ok
