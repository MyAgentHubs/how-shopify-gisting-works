import json
from typing import Any

import pytest
from eval_support import found_result, grader, verdict_of

from gisting.eval.found_copy import sentence_limit
from gisting.eval.found_facts import FoundFacts, parse_found
from gisting.prompt.phrases import load_phrases

PHRASES = load_phrases()
S = PHRASES.sentences
CLOSING = f"{S['thanks_patience']} {S['handoff_offer']}"
FIVE = (
    "It is with Test Parcel. Tracking number TP-5257262993. "
    "Expected delivery: October 5. It is on time."
)
WORDS = {
    "DELAYED": "Your order is delayed.",
    "ATTEMPTED_DELIVERY": "Sorry, a delivery attempt was unsuccessful.",
    "IN_TRANSIT": "Your order is on its way.",
    "OUT_FOR_DELIVERY": "Your order is out for delivery.",
}


def facts_of(scenario: str) -> FoundFacts | None:
    result = found_result(scenario)
    return parse_found(json.dumps(result))


def spec(scenario: str) -> dict[str, Any]:
    return {
        "kind": "second",
        "category": "found",
        "scenario": scenario,
        "result": {"found": scenario},
    }


def flagged(scenario: str, text: str) -> bool:
    return any(
        p.startswith("too_many_sentences") for p in verdict_of(spec(scenario), text).problems
    )


@pytest.mark.parametrize(
    ("scenario", "expected"),
    [
        ("IN_TRANSIT", 4),
        ("OUT_FOR_DELIVERY", 4),
        ("DELIVERED", 4),
        ("FULFILLED_NO_TRACKING", 4),
        ("DELAYED", 5),
        ("ATTEMPTED_DELIVERY", 5),
        ("PARTIALLY_FULFILLED", 5),
    ],
)
def test_the_sentence_limit_of_a_reply_is_the_one_of_its_line_in_the_data(
    scenario: str, expected: int
) -> None:
    facts = facts_of(scenario)
    assert facts is not None
    assert sentence_limit(facts, grader()) == expected
    assert sentence_limit(None, grader()) == PHRASES.limits.max_sentences


@pytest.mark.parametrize("scenario", ["DELAYED", "ATTEMPTED_DELIVERY"])
def test_a_line_with_a_larger_limit_may_have_five_content_sentences(scenario: str) -> None:
    text = f"{WORDS[scenario]} {FIVE} {CLOSING}"
    assert not flagged(scenario, text)


@pytest.mark.parametrize("scenario", ["IN_TRANSIT", "OUT_FOR_DELIVERY"])
def test_a_line_with_the_base_limit_may_not(scenario: str) -> None:
    assert flagged(scenario, f"{WORDS[scenario]} {FIVE}")


def test_a_sixth_content_sentence_is_too_many_even_for_a_line_with_the_larger_limit() -> None:
    assert flagged("DELAYED", f"{WORDS['DELAYED']} {FIVE} It is fine. {CLOSING}")
