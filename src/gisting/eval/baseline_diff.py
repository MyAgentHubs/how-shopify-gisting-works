from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from gisting.eval.baseline import Baseline
from gisting.eval.baseline_update import RATE_DIGITS, better
from gisting.eval.registry import Metric

EpochKey = tuple[str, str, str]
RECORD = "record"
GUARDED_FIELDS = ("gate", "direction", "tolerance", "min_cases")


@dataclass(frozen=True)
class RejudgedReport:
    directory: str
    values: Mapping[str, float | None]


ReportsOf = Callable[[EpochKey], Sequence[RejudgedReport]]


@dataclass(frozen=True)
class Unchanged:
    pass


@dataclass(frozen=True)
class Tighten:
    report_dir: str


@dataclass(frozen=True)
class Refresh:
    report_dir: str


@dataclass(frozen=True)
class NeedsSignature:
    reasons: tuple[str, ...]


Classification = Unchanged | Tighten | Refresh | NeedsSignature


@dataclass(frozen=True)
class ValueChange:
    key: EpochKey
    metric: str
    old: float | None
    new: float | None


def label(key: EpochKey) -> str:
    return "/".join(key)


def guarded(metric: Metric) -> tuple[str, str, int | None, int | None]:
    return metric.gate, metric.direction, metric.tolerance, metric.min_cases


def registry_reasons(old: Sequence[Metric], new: Sequence[Metric]) -> list[str]:
    before, after = {item.name: item for item in old}, {item.name: item for item in new}
    found = [
        f"metric {name} was removed from metrics.toml"
        for name in sorted(before.keys() - after.keys())
    ]
    found += [
        f"metric {name} was added to metrics.toml" for name in sorted(after.keys() - before.keys())
    ]
    for name in sorted(before.keys() & after.keys()):
        for field, was, now in zip(
            GUARDED_FIELDS, guarded(before[name]), guarded(after[name]), strict=True
        ):
            if was != now:
                found.append(f"metric {name}: {field} changed from {was!r} to {now!r}")
    return found


def structure_reasons(old: Baseline, new: Baseline) -> list[str]:
    before, after = {item.key: item for item in old.epochs}, {item.key: item for item in new.epochs}
    found = [f"epoch {label(key)} is new" for key in sorted(after.keys() - before.keys())]
    found += [f"epoch {label(key)} was deleted" for key in sorted(before.keys() - after.keys())]
    for key in sorted(before.keys() & after.keys()):
        was, now = set(before[key].metrics), set(after[key].metrics)
        found += [f"metric {n} was deleted from epoch {label(key)}" for n in sorted(was - now)]
        found += [f"metric {n} was added to epoch {label(key)}" for n in sorted(now - was)]
    return found


def value_changes(old: Baseline, new: Baseline) -> list[ValueChange]:
    before, after = {item.key: item for item in old.epochs}, {item.key: item for item in new.epochs}
    return [
        ValueChange(key, name, before[key].metrics[name], after[key].metrics[name])
        for key in sorted(before.keys() & after.keys())
        for name in sorted(before[key].metrics.keys() & after[key].metrics.keys())
        if before[key].metrics[name] != after[key].metrics[name]
    ]


def change_reason(change: ValueChange, metrics: Mapping[str, Metric]) -> str | None:
    where = f"{change.metric} of epoch {label(change.key)}"
    registered = metrics.get(change.metric)
    if change.old is None or change.new is None:
        return f"{where} changed from {change.old} to {change.new}, and null is not comparable"
    if registered is None:
        return f"{where} is not registered in metrics.toml, so its direction is unknown"
    if registered.gate != RECORD and not better(registered, change.new, change.old):
        return f"{where} got worse: {change.old} -> {change.new}"
    return None


def same_value(left: float | None, right: float | None) -> bool:
    if left is None or right is None:
        return False
    return round(left, RATE_DIGITS) == round(right, RATE_DIGITS)


def find_source(
    changes: Sequence[ValueChange], reports_of: ReportsOf
) -> tuple[str | None, list[str]]:
    keys = sorted({change.key for change in changes})
    if len(keys) != 1:
        names = ", ".join(label(key) for key in keys)
        return None, [f"values of {len(keys)} epochs changed at once ({names}); no single source"]
    for report in sorted(reports_of(keys[0]), key=lambda item: item.directory):
        if all(same_value(report.values.get(item.metric), item.new) for item in changes):
            return report.directory, []
    names = ", ".join(sorted(change.metric for change in changes))
    reason = f"no committed report of epoch {label(keys[0])} holds the new values of {names}"
    return None, [reason]


def classify(
    old: Baseline,
    new: Baseline,
    old_metrics: Sequence[Metric],
    new_metrics: Sequence[Metric],
    reports_of: ReportsOf,
) -> Classification:
    registered = {item.name: item for item in new_metrics}
    changes = value_changes(old, new)
    reasons = [*registry_reasons(old_metrics, new_metrics), *structure_reasons(old, new)]
    reasons += [item for item in (change_reason(c, registered) for c in changes) if item]
    source: str | None = None
    if changes:
        source, missing = find_source(changes, reports_of)
        reasons += missing
    if reasons:
        return NeedsSignature(tuple(reasons))
    if source is None:
        return Unchanged()
    recorded_only = all(registered[change.metric].gate == RECORD for change in changes)
    return Refresh(source) if recorded_only else Tighten(source)
