from typing import get_args

from eval_support import grader

from gisting.tools.outcomes import (
    PolicyFound,
    PolicyHit,
    PolicyNoMatch,
    PolicyOutcome,
    PolicyUnavailable,
)
from gisting.tools.search_policy import render_policy

HIT = PolicyHit("KB1", "returns", "Return window", "Items can be returned within 14 days.")
SAMPLES: dict[type, PolicyOutcome] = {
    PolicyFound: PolicyFound((HIT,)),
    PolicyNoMatch: PolicyNoMatch(),
    PolicyUnavailable: PolicyUnavailable("index missing"),
}


def test_every_search_policy_outcome_type_has_a_sample() -> None:
    assert set(SAMPLES) == set(get_args(PolicyOutcome))


def test_the_grader_policy_statuses_are_exactly_what_search_policy_renders() -> None:
    rendered = {str(render_policy(outcome)["status"]) for outcome in SAMPLES.values()}
    assert len(rendered) == len(SAMPLES)
    assert grader().policy_statuses == rendered
