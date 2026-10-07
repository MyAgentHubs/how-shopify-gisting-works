import json
from collections.abc import Sequence
from dataclasses import dataclass

from gisting.eval.baseline import Baseline, Epoch, Mode
from gisting.eval.registry import Metric
from gisting.eval.stats import mcnemar_p

ALPHA = 0.05
GATED = ("redline", "ratchet")
JSON_INDENT = 2
RATE_DIGITS = 6


class UpdateRefused(ValueError):
    pass


@dataclass(frozen=True)
class Candidate:
    backend_id: str
    rules_version: str
    mode: Mode
    values: dict[str, float | None]
    failed: dict[str, dict[str, bool]]
    whole: dict[str, dict[str, bool]]


@dataclass(frozen=True)
class Change:
    metric: str
    old: float | None
    new: float | None
    action: str
    detail: str = ""


def better(metric: Metric, new: float, old: float) -> bool:
    return new < old if metric.direction == "down" else new > old


def paired_counts(before: dict[str, bool], after: dict[str, bool]) -> tuple[int, int]:
    shared = before.keys() & after.keys()
    worse_before = sum(1 for case in shared if before[case] and not after[case])
    worse_after = sum(1 for case in shared if after[case] and not before[case])
    return worse_before, worse_after


def gated_change(
    metric: Metric, old: float, new: float, after: Candidate, before: Candidate | None
) -> Change:
    if new == old:
        return Change(metric.name, old, new, "kept", "unchanged")
    if not better(metric, new, old):
        message = (
            f"{metric.name} went from {old} to {new}; loosening a baseline needs the user's "
            "signature over the diff hash and cannot be done with this command"
        )
        raise UpdateRefused(message)
    if before is None:
        message = (
            f"{metric.name} improved; pass --before, the run that set {old}, for the paired test"
        )
        raise UpdateRefused(message)
    gained, lost = paired_counts(
        before.failed.get(metric.name, {}), after.failed.get(metric.name, {})
    )
    p_value = mcnemar_p(gained, lost)
    detail = f"{gained} cases fixed, {lost} broken, p={p_value:.3g}"
    if lost < gained and p_value < ALPHA:
        return Change(metric.name, old, new, "tightened", detail)
    return Change(metric.name, old, old, "kept", f"improvement not significant ({detail})")


def one_change(
    metric: Metric, old: float | None, after: Candidate, before: Candidate | None
) -> Change | None:
    new = after.values.get(metric.name)
    if metric.name not in after.values:
        return None
    if old is None or new is None:
        return Change(metric.name, old, new, "new")
    if metric.gate not in GATED:
        return Change(metric.name, old, new, "recorded")
    return gated_change(metric, old, new, after, before)


def decide(
    old: Epoch | None, after: Candidate, before: Candidate | None, metrics: Sequence[Metric]
) -> tuple[dict[str, float | None], list[Change]]:
    if before is not None and (before.backend_id, before.rules_version, before.mode) != (
        after.backend_id,
        after.rules_version,
        after.mode,
    ):
        message = (
            "the --before run is from another backend, rules epoch or mode; "
            "epochs are never compared"
        )
        raise UpdateRefused(message)
    values: dict[str, float | None] = dict(old.metrics) if old else {}
    changes: list[Change] = []
    for metric in metrics:
        change = one_change(metric, old.metrics.get(metric.name) if old else None, after, before)
        if change is None:
            continue
        values[metric.name] = change.new
        changes.append(change)
    return values, changes


def with_epoch(baseline: Baseline, epoch: Epoch) -> Baseline:
    others = tuple(item for item in baseline.epochs if item.key != epoch.key)
    return Baseline(baseline.version, tuple(sorted((*others, epoch), key=lambda item: item.key)))


def dump_baseline(baseline: Baseline) -> str:
    document = {
        "version": baseline.version,
        "epochs": [
            {
                "backend_id": e.backend_id,
                "rules_version": e.rules_version,
                "mode": e.mode,
                "metrics": e.metrics,
            }
            for e in baseline.epochs
        ],
    }
    return json.dumps(document, indent=JSON_INDENT, sort_keys=True) + "\n"
