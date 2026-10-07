import dataclasses
from collections.abc import Sequence
from pathlib import Path

from gisting.eval.baseline import Baseline, Epoch, Mode, load_baseline
from gisting.eval.baseline_diff import (
    Classification,
    EpochKey,
    NeedsSignature,
    Refresh,
    RejudgedReport,
    ReportsOf,
    Tighten,
    Unchanged,
    classify,
)
from gisting.eval.registry import Metric, load_registry

REPO = Path(__file__).resolve().parents[2]
BACKEND, RULES = "backend-one", "rules-one"
FULL, GIST = (BACKEND, RULES, "full"), (BACKEND, RULES, "gist")
REPORT = "eval/reports/aaaa/full"
OTHER_REPORT = "eval/reports/bbbb/full"


def metric(name: str, gate: str = "ratchet", direction: str = "down") -> Metric:
    tolerance = None if gate == "record" else 0
    min_cases = 100 if gate == "redline" else None
    return Metric(name, gate, direction, "J1", tolerance, min_cases, None, None, None)


METRICS = [
    metric("red", "redline"),
    metric("over_refusal"),
    metric("guard"),
    metric("coverage", direction="up"),
    metric("tokens", "record"),
]
VALUES: dict[str, float | None] = {
    "red": 0.0,
    "over_refusal": 0.2,
    "guard": 0.3,
    "coverage": 0.8,
    "tokens": 100.0,
}


def epoch(mode: Mode = "full", rules: str = RULES, **changes: float | None) -> Epoch:
    return Epoch(BACKEND, rules, mode, {**VALUES, **changes})


def baseline(*epochs: Epoch) -> Baseline:
    return Baseline(1, tuple(epochs))


def nothing(_key: EpochKey) -> list[RejudgedReport]:
    return []


def reports(*items: RejudgedReport) -> ReportsOf:
    def lookup(key: EpochKey) -> list[RejudgedReport]:
        return list(items) if key == FULL else []

    return lookup


def report(directory: str = REPORT, **changes: float | None) -> RejudgedReport:
    return RejudgedReport(directory, {**VALUES, **changes})


def classified(
    old: Baseline,
    new: Baseline,
    lookup: ReportsOf = nothing,
    metrics: Sequence[Metric] = METRICS,
) -> Classification:
    return classify(old, new, METRICS, metrics, lookup)


def reasons_of(result: object) -> tuple[str, ...]:
    assert isinstance(result, NeedsSignature), result
    return result.reasons


def test_the_same_baseline_is_unchanged() -> None:
    assert classified(baseline(epoch(), epoch("gist")), baseline(epoch(), epoch("gist"))) == (
        Unchanged()
    )


def test_a_reordered_but_equal_baseline_is_unchanged() -> None:
    old, new = baseline(epoch(), epoch("gist")), baseline(epoch("gist"), epoch())
    assert classified(old, new) == Unchanged()


def test_a_better_value_that_a_committed_report_holds_is_a_tightening() -> None:
    old, new = baseline(epoch()), baseline(epoch(over_refusal=0.15))
    result = classified(old, new, reports(report(over_refusal=0.15)))
    assert result == Tighten(REPORT)


def test_several_better_values_from_the_same_report_are_a_tightening() -> None:
    old = baseline(epoch())
    new = baseline(epoch(over_refusal=0.15, guard=0.25, coverage=0.9, tokens=90.0))
    holds = report(over_refusal=0.15, guard=0.25, coverage=0.9, tokens=90.0)
    assert classified(old, new, reports(holds)) == Tighten(REPORT)


def test_the_report_that_holds_every_changed_value_is_the_one_named() -> None:
    old, new = baseline(epoch()), baseline(epoch(over_refusal=0.15, guard=0.25))
    lookup = reports(report(OTHER_REPORT, over_refusal=0.15), report(guard=0.25, over_refusal=0.15))
    assert classified(old, new, lookup) == Tighten(REPORT)


def test_values_are_compared_at_the_precision_the_baseline_file_is_written_with() -> None:
    old, new = baseline(epoch()), baseline(epoch(over_refusal=0.152174))
    holds = report(over_refusal=0.15217391304347827)
    assert classified(old, new, reports(holds)) == Tighten(REPORT)


def test_a_value_that_no_report_holds_needs_a_signature() -> None:
    old, new = baseline(epoch()), baseline(epoch(over_refusal=0.15))
    result = classified(old, new, reports(report(over_refusal=0.16)))
    assert any("no committed report" in item for item in reasons_of(result))


def test_a_value_without_any_report_of_the_epoch_needs_a_signature() -> None:
    old, new = baseline(epoch()), baseline(epoch(over_refusal=0.15))
    assert any("no committed report" in item for item in reasons_of(classified(old, new)))


def test_values_taken_from_two_different_reports_need_a_signature() -> None:
    old, new = baseline(epoch()), baseline(epoch(over_refusal=0.15, guard=0.25))
    lookup = reports(report(OTHER_REPORT, over_refusal=0.15), report(guard=0.25))
    assert any("no committed report" in item for item in reasons_of(classified(old, new, lookup)))


def test_a_report_of_another_epoch_is_not_a_source() -> None:
    old, new = baseline(epoch()), baseline(epoch(over_refusal=0.15))

    def lookup(key: EpochKey) -> list[RejudgedReport]:
        return [report(over_refusal=0.15)] if key == GIST else []

    assert any("no committed report" in item for item in reasons_of(classified(old, new, lookup)))


def test_a_worse_value_needs_a_signature_even_when_a_report_holds_it() -> None:
    old, new = baseline(epoch()), baseline(epoch(guard=0.35))
    found = reasons_of(classified(old, new, reports(report(guard=0.35))))
    assert len(found) == 1
    assert "guard" in found[0] and "worse" in found[0]


def test_a_worse_value_of_an_up_metric_needs_a_signature() -> None:
    old, new = baseline(epoch()), baseline(epoch(coverage=0.7))
    assert any("coverage" in item for item in reasons_of(classified(old, new)))


def test_one_worse_value_among_better_ones_needs_a_signature() -> None:
    old = baseline(epoch())
    new = baseline(epoch(over_refusal=0.1, guard=0.35))
    holds = report(over_refusal=0.1, guard=0.35)
    found = reasons_of(classified(old, new, reports(holds)))
    assert len(found) == 1 and "guard" in found[0]


def test_a_new_epoch_needs_a_signature() -> None:
    old, new = baseline(epoch()), baseline(epoch(), epoch("gist"))
    found = reasons_of(classified(old, new))
    assert found == (f"epoch {'/'.join(GIST)} is new",)


def test_a_forged_rules_version_epoch_needs_a_signature() -> None:
    old, new = baseline(epoch()), baseline(epoch(), epoch(rules="forged"))
    assert any("is new" in item for item in reasons_of(classified(old, new)))


def test_a_deleted_epoch_needs_a_signature() -> None:
    old, new = baseline(epoch(), epoch("gist")), baseline(epoch())
    assert reasons_of(classified(old, new)) == (f"epoch {'/'.join(GIST)} was deleted",)


def test_deleting_an_epoch_and_building_another_in_one_diff_lists_both() -> None:
    old, new = baseline(epoch()), baseline(epoch(rules="other"))
    found = reasons_of(classified(old, new))
    assert any("is new" in item for item in found)
    assert any("was deleted" in item for item in found)


def test_rebuilding_a_deleted_epoch_needs_a_signature_in_both_steps() -> None:
    full = baseline(epoch(), epoch("gist"))
    deleted = baseline(epoch())
    rebuilt = baseline(epoch(), epoch("gist", over_refusal=0.0, guard=0.0))
    assert any("was deleted" in item for item in reasons_of(classified(full, deleted)))
    assert any("is new" in item for item in reasons_of(classified(deleted, rebuilt)))


def test_a_deleted_metric_needs_a_signature() -> None:
    values = {name: value for name, value in VALUES.items() if name != "guard"}
    old, new = baseline(epoch()), baseline(Epoch(BACKEND, RULES, "full", values))
    assert any("guard was deleted" in item for item in reasons_of(classified(old, new)))


def test_an_added_metric_needs_a_signature() -> None:
    values = {name: value for name, value in VALUES.items() if name != "guard"}
    old, new = baseline(Epoch(BACKEND, RULES, "full", values)), baseline(epoch())
    assert any("guard was added" in item for item in reasons_of(classified(old, new)))


def test_a_value_that_becomes_null_or_stops_being_null_needs_a_signature() -> None:
    old, new = baseline(epoch()), baseline(epoch(guard=None))
    assert any("null" in item for item in reasons_of(classified(old, new)))
    assert any("null" in item for item in reasons_of(classified(new, old)))


def test_a_changed_metric_missing_from_the_registry_needs_a_signature() -> None:
    old, new = baseline(epoch()), baseline(epoch(guard=0.1))
    short = [item for item in METRICS if item.name != "guard"]
    assert any("not registered" in item for item in reasons_of(classified(old, new, metrics=short)))


def test_every_change_to_a_guarded_registry_field_needs_a_signature() -> None:
    same = baseline(epoch())
    changes = [
        dataclasses.replace(METRICS[1], gate="record"),
        dataclasses.replace(METRICS[1], direction="up"),
        dataclasses.replace(METRICS[1], tolerance=3),
        dataclasses.replace(METRICS[0], min_cases=1),
    ]
    for changed in changes:
        edited = [changed if item.name == changed.name else item for item in METRICS]
        found = reasons_of(classified(same, same, metrics=edited))
        assert len(found) == 1 and changed.name in found[0]


def test_adding_or_removing_a_registered_metric_needs_a_signature() -> None:
    same = baseline(epoch())
    added = [*METRICS, metric("fresh")]
    removed = METRICS[:-1]
    assert any("fresh" in item for item in reasons_of(classified(same, same, metrics=added)))
    assert any("tokens" in item for item in reasons_of(classified(same, same, metrics=removed)))


def test_a_change_of_text_fields_in_the_registry_needs_no_signature() -> None:
    same = baseline(epoch())
    reworded = [dataclasses.replace(item, where_to_look="elsewhere") for item in METRICS]
    assert classified(same, same, metrics=reworded) == Unchanged()


def test_changes_in_two_epochs_at_once_have_no_single_source() -> None:
    old = baseline(epoch(), epoch("gist"))
    new = baseline(epoch(over_refusal=0.15), epoch("gist", over_refusal=0.15))
    found = reasons_of(classified(old, new, reports(report(over_refusal=0.15))))
    assert len(found) == 1 and "2 epochs" in found[0]


def test_swapping_the_values_of_two_epochs_needs_a_signature() -> None:
    full, gist = epoch(guard=0.3, over_refusal=0.2), epoch("gist", guard=0.4, over_refusal=0.1)
    swapped = baseline(
        dataclasses.replace(full, metrics=gist.metrics),
        dataclasses.replace(gist, metrics=full.metrics),
    )
    found = reasons_of(classified(baseline(full, gist), swapped))
    assert any("worse" in item for item in found)
    assert any("2 epochs" in item for item in found)


def test_every_reason_is_listed() -> None:
    old = baseline(epoch(), epoch("gist"))
    new = baseline(epoch(guard=0.4), epoch(rules="forged"))
    found = reasons_of(classified(old, new))
    assert any("worse" in item for item in found)
    assert any("is new" in item for item in found)
    assert any("was deleted" in item for item in found)
    assert any("no committed report" in item for item in found)


def real_files() -> tuple[Baseline, list[Metric]]:
    metrics, problems = load_registry(REPO / "eval" / "metrics.toml")
    assert problems == []
    return load_baseline(REPO / "eval" / "baseline.json"), metrics


def test_the_reviewer_repro_of_two_worse_gist_values_from_an_old_report_needs_a_signature() -> None:
    current, metrics = real_files()
    (gist,) = [item for item in current.epochs if item.mode == "gist"]
    forged = dataclasses.replace(
        gist,
        metrics={
            **gist.metrics,
            "unsafe_compliance_failures": 0.14,
            "fact_provenance_failures": 0.00431,
        },
    )
    old_report = RejudgedReport("eval/reports/old/gist", forged.metrics)
    new = Baseline(1, tuple(forged if item is gist else item for item in current.epochs))
    result = classify(current, new, metrics, metrics, lambda key: [old_report])
    found = reasons_of(result)
    assert len([item for item in found if "worse" in item]) == 2


def test_the_committed_baseline_against_itself_is_unchanged() -> None:
    current, metrics = real_files()
    assert classify(current, current, metrics, metrics, nothing) == Unchanged()


def test_a_recorded_metric_that_got_worse_follows_its_report_without_a_signature() -> None:
    old, new = baseline(epoch()), baseline(epoch(tokens=120.0))
    assert classified(old, new, reports(report(tokens=120.0))) == Refresh(REPORT)


def test_a_recorded_metric_that_got_better_is_a_refresh_too() -> None:
    old, new = baseline(epoch()), baseline(epoch(tokens=80.0))
    assert classified(old, new, reports(report(tokens=80.0))) == Refresh(REPORT)


def test_a_recorded_change_riding_with_a_better_gated_one_is_a_tightening() -> None:
    old, new = baseline(epoch()), baseline(epoch(over_refusal=0.15, tokens=120.0))
    holds = report(over_refusal=0.15, tokens=120.0)
    assert classified(old, new, reports(holds)) == Tighten(REPORT)


def test_a_recorded_change_with_no_source_report_needs_a_signature() -> None:
    old, new = baseline(epoch()), baseline(epoch(tokens=120.0))
    assert any("no committed report" in item for item in reasons_of(classified(old, new)))
    other = reports(report(tokens=130.0))
    assert any("no committed report" in item for item in reasons_of(classified(old, new, other)))


def test_a_recorded_change_does_not_hide_behind_a_report_of_the_gated_one() -> None:
    old, new = baseline(epoch()), baseline(epoch(over_refusal=0.15, tokens=120.0))
    lookup = reports(report(OTHER_REPORT, over_refusal=0.15), report(tokens=120.0))
    assert any("no committed report" in item for item in reasons_of(classified(old, new, lookup)))


def test_a_worse_gated_value_still_needs_a_signature_next_to_a_recorded_change() -> None:
    old, new = baseline(epoch()), baseline(epoch(guard=0.35, tokens=120.0))
    found = reasons_of(classified(old, new, reports(report(guard=0.35, tokens=120.0))))
    assert len(found) == 1 and "guard" in found[0]


def test_recorded_changes_in_two_epochs_have_no_single_source() -> None:
    old = baseline(epoch(), epoch("gist"))
    new = baseline(epoch(tokens=120.0), epoch("gist", tokens=120.0))
    found = reasons_of(classified(old, new, reports(report(tokens=120.0))))
    assert any("2 epochs" in item for item in found)


def test_adding_or_deleting_a_recorded_metric_needs_a_signature() -> None:
    values = {name: value for name, value in VALUES.items() if name != "tokens"}
    without = baseline(Epoch(BACKEND, RULES, "full", values))
    full = baseline(epoch())
    assert any("tokens was deleted" in item for item in reasons_of(classified(full, without)))
    assert any("tokens was added" in item for item in reasons_of(classified(without, full)))


def test_a_recorded_value_that_becomes_null_needs_a_signature() -> None:
    old, new = baseline(epoch()), baseline(epoch(tokens=None))
    assert any("null" in item for item in reasons_of(classified(old, new)))


def test_a_recorded_metric_missing_from_the_registry_needs_a_signature() -> None:
    old, new = baseline(epoch()), baseline(epoch(tokens=120.0))
    short = [item for item in METRICS if item.name != "tokens"]
    found = reasons_of(classified(old, new, reports(report(tokens=120.0)), metrics=short))
    assert any("not registered" in item for item in found)


def test_relaxing_a_gated_metric_to_recorded_to_excuse_a_worse_value_needs_a_signature() -> None:
    old, new = baseline(epoch()), baseline(epoch(guard=0.35))
    relaxed = [
        dataclasses.replace(item, gate="record") if item.name == "guard" else item
        for item in METRICS
    ]
    found = reasons_of(classified(old, new, reports(report(guard=0.35)), metrics=relaxed))
    assert any("gate changed" in item for item in found)
