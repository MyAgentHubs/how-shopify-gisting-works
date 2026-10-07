import dataclasses

import pytest

from gisting.eval.baseline import Baseline, Epoch, EpochMismatch, Mode, metric_delta
from gisting.eval.baseline_update import Candidate
from gisting.eval.ratchet import Verdict, Violation, judge
from gisting.eval.registry import Metric

BACKEND, RULES = "backend-one", "rules-one"
N = 100


def metric(
    name: str,
    gate: str = "ratchet",
    direction: str = "down",
    tolerance: int | None = 0,
    min_cases: int | None = None,
) -> Metric:
    return Metric(name, gate, direction, "J1", tolerance, min_cases, None, None, None)


REDLINE = metric("red", "redline", min_cases=50)
RATE = metric("rate")
LOOSE = metric("loose", tolerance=2)
UP = metric("coverage", direction="up")
TOKENS = metric("tokens", "record", tolerance=None)
ALL = [REDLINE, RATE, LOOSE, UP, TOKENS]
GOOD_VALUES: dict[str, float | None] = {
    "red": 0.0,
    "rate": 0.2,
    "loose": 0.2,
    "coverage": 0.8,
    "tokens": 100.0,
}


def baseline_of(*epochs: Epoch) -> Baseline:
    return Baseline(1, tuple(epochs))


def epoch(mode: Mode = "full", **changes: float | None) -> Epoch:
    return Epoch(BACKEND, RULES, mode, {**GOOD_VALUES, **changes})


def candidate(mode: Mode = "full", n: int = N, **changes: float | None) -> Candidate:
    values = {**GOOD_VALUES, **changes}
    flags: dict[str, dict[str, bool]] = {}
    for item in ALL:
        value = values.get(item.name)
        if item.gate != "record" and value is not None:
            flags[item.name] = {f"case{i}": i < round(value * n) for i in range(n)}
    whole = {name: dict(cases) for name, cases in flags.items()}
    return Candidate(BACKEND, RULES, mode, values, flags, whole)


def kinds(verdict: Verdict) -> list[tuple[str, str]]:
    return [(item.metric, item.kind) for item in verdict.violations]


def test_a_report_equal_to_its_baseline_has_no_violations() -> None:
    verdict = judge(candidate(), baseline_of(epoch()), ALL)
    assert verdict.violations == ()
    assert verdict.has_baseline


def test_a_better_report_has_no_violations() -> None:
    verdict = judge(candidate(rate=0.1, coverage=0.9), baseline_of(epoch()), ALL)
    assert verdict.violations == ()


def test_one_case_worse_than_the_baseline_is_a_violation() -> None:
    verdict = judge(candidate(rate=0.21), baseline_of(epoch()), ALL)
    assert kinds(verdict) == [("rate", "regressed")]
    (found,) = verdict.violations
    assert (found.value, found.baseline, found.n) == (0.21, 0.2, N)


def test_a_worse_value_of_an_up_metric_is_a_violation() -> None:
    verdict = judge(candidate(coverage=0.79), baseline_of(epoch()), ALL)
    assert kinds(verdict) == [("coverage", "regressed")]


def test_a_tolerance_of_cases_is_allowed_and_one_more_is_not() -> None:
    within = judge(candidate(loose=0.22), baseline_of(epoch()), ALL)
    beyond = judge(candidate(loose=0.23), baseline_of(epoch()), ALL)
    assert within.violations == ()
    assert kinds(beyond) == [("loose", "regressed")]


def test_the_tolerance_counts_cases_so_it_shrinks_with_more_cases() -> None:
    wide = judge(candidate(n=200, loose=0.21), baseline_of(epoch()), ALL)
    assert wide.violations == ()
    tight = judge(candidate(n=1000, loose=0.203), baseline_of(epoch(loose=0.2)), ALL)
    assert kinds(tight) == [("loose", "regressed")]


@pytest.mark.parametrize(("failures", "bad"), [(35, False), (36, True)])
def test_a_tolerance_of_two_cases_holds_exactly_where_the_rates_do_not_round_evenly(
    failures: int, bad: bool
) -> None:
    old = baseline_of(epoch(loose=round(33 / 300, 6)))
    new = candidate(n=300, loose=round(failures / 300, 6))
    assert (kinds(judge(new, old, ALL)) == [("loose", "regressed")]) is bad


@pytest.mark.parametrize(("failures", "bad"), [(102, False), (103, True)])
def test_the_rounding_of_a_repeating_baseline_rate_does_not_cost_a_case(
    failures: int, bad: bool
) -> None:
    old = baseline_of(epoch(loose=round(100 / 300, 6)))
    new = candidate(n=300, loose=round(failures / 300, 6))
    assert (kinds(judge(new, old, ALL)) == [("loose", "regressed")]) is bad


def test_an_up_metric_is_compared_in_cases_with_the_same_tolerance() -> None:
    free = metric("coverage", direction="up", tolerance=2)
    old = baseline_of(epoch(coverage=round(190 / 300, 6)))
    within = judge(candidate(n=300, coverage=round(188 / 300, 6)), old, [free])
    beyond = judge(candidate(n=300, coverage=round(187 / 300, 6)), old, [free])
    assert within.violations == ()
    assert kinds(beyond) == [("coverage", "regressed")]


def test_a_baseline_rate_from_more_cases_is_scaled_to_the_cases_of_the_report() -> None:
    old = baseline_of(epoch(loose=0.2))
    assert judge(candidate(n=200, loose=0.21), old, ALL).violations == ()
    assert kinds(judge(candidate(n=200, loose=0.215), old, ALL)) == [("loose", "regressed")]


def test_a_rounded_rate_equal_to_the_baseline_passes() -> None:
    third = round(1 / 3, 6)
    old = baseline_of(epoch(rate=third))
    assert judge(candidate(n=3, rate=third), old, [RATE]).violations == ()


def test_a_redline_with_one_failure_is_a_violation_whatever_the_baseline_says() -> None:
    verdict = judge(candidate(red=0.01), baseline_of(epoch(red=0.01)), ALL)
    assert kinds(verdict) == [("red", "redline_failures")]


def test_a_redline_failure_is_counted_from_the_cases_not_from_the_dev_value() -> None:
    flags = {f"c{i}": i == 0 for i in range(300)}
    rounded = dataclasses.replace(candidate(n=300), whole={"red": flags})
    assert rounded.values["red"] == 0.0
    assert kinds(judge(rounded, baseline_of(epoch()), ALL)) == [("red", "redline_failures")]


def test_a_redline_failure_outside_the_dev_cases_is_a_violation() -> None:
    dev_clean = candidate(n=N)
    train = {f"train{i}": i == 0 for i in range(N)}
    whole = {"red": {**dev_clean.failed["red"], **train}}
    verdict = judge(dataclasses.replace(dev_clean, whole=whole), baseline_of(epoch()), ALL)
    assert kinds(verdict) == [("red", "redline_failures")]
    (found,) = verdict.violations
    assert found.n == 2 * N


def test_too_few_dev_cases_are_enough_when_the_whole_report_has_enough() -> None:
    small_dev = candidate(n=40)
    others = {f"train{i}": False for i in range(60)}
    whole = {"red": {**small_dev.failed["red"], **others}}
    verdict = judge(dataclasses.replace(small_dev, whole=whole), baseline_of(epoch()), ALL)
    assert verdict.violations == ()


def test_too_few_cases_in_the_whole_report_are_a_violation_even_if_dev_alone_has_enough() -> None:
    dev = candidate(n=60)
    whole = {"red": {name: False for name in list(dev.failed["red"])[:40]}}
    verdict = judge(dataclasses.replace(dev, whole=whole), baseline_of(epoch()), ALL)
    assert kinds(verdict) == [("red", "redline_too_few_cases")]


def test_a_redline_the_whole_report_did_not_measure_is_a_violation() -> None:
    bare = dataclasses.replace(candidate(), whole={})
    assert ("red", "not_measured") in kinds(judge(bare, baseline_of(epoch()), ALL))


def test_a_ratchet_metric_is_still_judged_on_the_dev_cases() -> None:
    dev = candidate(rate=0.2)
    train_worse = {f"train{i}": True for i in range(N)}
    whole = {**dev.whole, "rate": {**dev.failed["rate"], **train_worse}}
    assert judge(dataclasses.replace(dev, whole=whole), baseline_of(epoch()), ALL).violations == ()


def test_a_redline_with_too_few_cases_is_a_violation() -> None:
    enough = judge(candidate(n=50), baseline_of(epoch()), ALL)
    short = judge(candidate(n=49), baseline_of(epoch()), ALL)
    assert ("red", "redline_too_few_cases") not in kinds(enough)
    assert ("red", "redline_too_few_cases") in kinds(short)


def test_a_redline_without_a_registered_minimum_needs_no_case_count() -> None:
    free = metric("red", "redline", min_cases=None)
    verdict = judge(candidate(n=1), baseline_of(epoch()), [free])
    assert verdict.violations == ()


def test_a_record_metric_is_never_judged() -> None:
    verdict = judge(candidate(tokens=100000.0), baseline_of(epoch()), ALL)
    assert verdict.violations == ()


def test_an_epoch_of_another_mode_is_not_compared() -> None:
    verdict = judge(candidate("gist", rate=0.9), baseline_of(epoch("full")), ALL)
    assert not verdict.has_baseline
    assert verdict.violations == ()


def test_an_epoch_of_another_backend_or_rules_version_is_not_compared() -> None:
    other_backend = Epoch("elsewhere", RULES, "full", GOOD_VALUES)
    other_rules = Epoch(BACKEND, "rules-two", "full", GOOD_VALUES)
    for old in (other_backend, other_rules):
        verdict = judge(candidate(rate=0.9), baseline_of(old), ALL)
        assert not verdict.has_baseline
        assert verdict.violations == ()


def test_a_redline_is_still_judged_when_the_epoch_has_no_baseline() -> None:
    verdict = judge(candidate("gist", red=0.01), baseline_of(epoch("full")), ALL)
    assert not verdict.has_baseline
    assert kinds(verdict) == [("red", "redline_failures")]


def test_the_epoch_key_of_the_verdict_names_the_judged_epoch() -> None:
    verdict = judge(candidate("gist"), baseline_of(), ALL)
    assert verdict.key == (BACKEND, RULES, "gist")


def test_a_gated_metric_the_report_did_not_measure_is_a_violation() -> None:
    verdict = judge(candidate(rate=None), baseline_of(epoch()), ALL)
    assert kinds(verdict) == [("rate", "not_measured")]


def test_a_gated_metric_the_baseline_does_not_hold_is_a_violation() -> None:
    for gap in ({"rate": None}, {}):
        values = {name: value for name, value in GOOD_VALUES.items() if name != "rate"}
        old = Epoch(BACKEND, RULES, "full", {**values, **gap})
        assert kinds(judge(candidate(), baseline_of(old), ALL)) == [("rate", "baseline_missing")]


def test_a_violation_describes_itself() -> None:
    text = Violation("rate", "regressed", 0.21, 0.2, N).describe()
    assert "rate" in text and "0.21" in text and "0.2" in text


def test_comparing_epochs_of_different_keys_is_refused() -> None:
    with pytest.raises(EpochMismatch):
        metric_delta(epoch("full"), epoch("gist"), "rate")


def test_float_noise_in_the_difference_does_not_fail_a_value_exactly_at_the_tolerance() -> None:
    one_case = metric("rate", tolerance=1)
    old = baseline_of(epoch(rate=0.03))
    assert judge(candidate(rate=0.04), old, [one_case]).violations == ()
