import pytest

from gisting.eval.baseline import Baseline, Epoch
from gisting.eval.baseline_update import (
    Candidate,
    UpdateRefused,
    decide,
    dump_baseline,
    with_epoch,
)
from gisting.eval.registry import Metric

DOWN = "down"


def metric(name: str, gate: str = "ratchet") -> Metric:
    return Metric(name, gate, DOWN, "J1", 0, None, None, None, None)


METRICS = [metric("m"), metric("tokens", "record")]


def candidate(value: float | None, failed: dict[str, bool] | None = None) -> Candidate:
    flags = {"m": failed} if failed is not None else {}
    return Candidate("b", "r", "full", {"m": value, "tokens": 5.0}, flags, flags)


def epoch(value: float | None) -> Epoch:
    return Epoch("b", "r", "full", {"m": value, "tokens": 9.0})


def fails(count: int, total: int) -> dict[str, bool]:
    return {f"c{i}": i < count for i in range(total)}


def test_a_new_epoch_takes_every_measured_value() -> None:
    values, changes = decide(None, candidate(0.25, fails(5, 20)), None, METRICS)
    assert values == {"m": 0.25, "tokens": 5.0}
    assert {change.action for change in changes} == {"new"}


def test_a_metric_that_was_never_measured_takes_the_new_value() -> None:
    values, _ = decide(epoch(None), candidate(0.25, fails(5, 20)), None, METRICS)
    assert values["m"] == 0.25


def test_a_significant_paired_improvement_tightens_the_value() -> None:
    before, after = fails(10, 20), fails(0, 20)
    values, changes = decide(epoch(0.5), candidate(0.0, after), candidate(0.5, before), METRICS)
    assert values["m"] == 0.0
    change = next(item for item in changes if item.metric == "m")
    assert change.action == "tightened"
    assert "p=0.00195" in change.detail


def test_an_improvement_that_could_be_noise_leaves_the_value_alone() -> None:
    before, after = fails(1, 20), fails(0, 20)
    values, changes = decide(epoch(0.05), candidate(0.0, after), candidate(0.05, before), METRICS)
    assert values["m"] == 0.05
    change = next(item for item in changes if item.metric == "m")
    assert change.action == "kept"
    assert "not significant" in change.detail


def test_cases_that_got_worse_while_others_got_better_are_counted_in_the_test() -> None:
    before = {f"c{i}": i < 6 for i in range(20)}
    after = {f"c{i}": 6 <= i < 10 for i in range(20)}
    values, _ = decide(epoch(0.3), candidate(0.2, after), candidate(0.3, before), METRICS)
    assert values["m"] == 0.3


def test_an_improvement_needs_the_run_that_set_the_old_value() -> None:
    with pytest.raises(UpdateRefused, match="--before"):
        decide(epoch(0.5), candidate(0.0, fails(0, 20)), None, METRICS)


def test_a_worse_value_is_refused_because_loosening_needs_a_signature() -> None:
    with pytest.raises(UpdateRefused, match="signature"):
        decide(epoch(0.0), candidate(0.1, fails(2, 20)), candidate(0.0, fails(0, 20)), METRICS)


def test_the_same_value_changes_nothing_for_a_gated_metric() -> None:
    values, changes = decide(epoch(0.1), candidate(0.1, fails(2, 20)), None, METRICS)
    assert values["m"] == 0.1
    assert next(item for item in changes if item.metric == "m").action == "kept"


def test_a_record_metric_is_simply_rewritten() -> None:
    values, changes = decide(epoch(0.1), candidate(0.1, fails(2, 20)), None, METRICS)
    assert values["tokens"] == 5.0
    assert next(item for item in changes if item.metric == "tokens").action == "recorded"


def test_runs_from_two_epochs_are_never_compared() -> None:
    other = Candidate("b", "other-rules", "full", {"m": 0.0}, {"m": fails(0, 20)}, {})
    with pytest.raises(UpdateRefused, match="epoch"):
        decide(epoch(0.5), candidate(0.0, fails(0, 20)), other, METRICS)


def test_runs_from_the_two_modes_are_never_compared() -> None:
    gist = Candidate("b", "r", "gist", {"m": 0.0}, {"m": fails(0, 20)}, {})
    with pytest.raises(UpdateRefused, match="mode"):
        decide(epoch(0.5), candidate(0.0, fails(0, 20)), gist, METRICS)


def test_a_new_mode_does_not_replace_the_epoch_of_the_other_mode() -> None:
    full = Epoch("b", "r", "full", {"m": 0.5})
    gist = Epoch("b", "r", "gist", {"m": 0.9})
    baseline = with_epoch(with_epoch(Baseline(1, ()), full), gist)
    assert [item.key for item in baseline.epochs] == [("b", "r", "full"), ("b", "r", "gist")]
    assert baseline.epoch("b", "r", "full") == full
    assert dump_baseline(baseline).count('"mode"') == 2


def test_values_of_metrics_the_run_did_not_measure_are_kept() -> None:
    only_tokens = Candidate("b", "r", "full", {"tokens": 5.0}, {}, {})
    values, _ = decide(epoch(0.5), only_tokens, None, METRICS)
    assert values == {"m": 0.5, "tokens": 5.0}
