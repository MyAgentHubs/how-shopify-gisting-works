from pathlib import Path

import pytest
from audit_support import METRICS_TOML, Lab, culprits, messages, new_lab, run

METRICS = "eval/metrics.toml"
RECORD_ONLY = '[[metric]]\nname = "extra"\ngate = "record"\ndirection = "down"\njourney = "J1"\n'
BROKEN = {
    "an empty registry": ("# nothing registered\n", "no metrics registered"),
    "invalid TOML": ("[[metric]\nname =", "invalid TOML"),
    "a redline without min_cases": (
        METRICS_TOML.replace("min_cases = 100\n", ""),
        "min_cases must be a positive integer for a redline",
    ),
    "a redline with a tolerance": (
        METRICS_TOML.replace("tolerance = 0\nmin_cases", "tolerance = 1\nmin_cases"),
        "tolerance of a redline must be 0",
    ),
    "a deeply nested value": ("a = " + "[" * 100_000 + "]" * 100_000, "unreadable"),
}


@pytest.fixture
def lab(tmp_path: Path) -> Lab:
    return new_lab(tmp_path)


@pytest.mark.parametrize(("text", "problem"), list(BROKEN.values()), ids=list(BROKEN))
def test_a_signed_commit_that_breaks_the_registry_is_still_a_finding(
    lab: Lab, text: str, problem: str
) -> None:
    lab.genesis()
    bad = lab.signed_commit({METRICS: text})
    result = run(lab)
    assert culprits(result) == {bad}
    assert problem in messages(result)


def test_a_signed_commit_that_removes_the_registry_is_a_finding(lab: Lab) -> None:
    lab.genesis()
    bad = lab.signed_commit({METRICS: None})
    result = run(lab)
    assert culprits(result) == {bad}
    assert f"has no {METRICS}" in messages(result)


def test_a_signed_valid_registry_change_is_no_finding(lab: Lab) -> None:
    lab.genesis()
    lab.signed_commit({METRICS: METRICS_TOML + RECORD_ONLY})
    assert run(lab).findings == ()


def test_the_broken_registry_is_flagged_once_at_the_commit_that_broke_it(lab: Lab) -> None:
    lab.genesis()
    bad = lab.signed_commit({METRICS: "# nothing registered\n"})
    lab.commit({"notes.txt": "later"})
    assert culprits(run(lab)) == {bad}
