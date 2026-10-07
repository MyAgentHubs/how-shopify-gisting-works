from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from gisting.eval.baseline import Baseline, Epoch
from gisting.eval.baseline_update import RATE_DIGITS, Candidate
from gisting.eval.registry import Metric

EPSILON = 1e-9
ROUNDING = 0.5 * 10**-RATE_DIGITS
Kind = Literal[
    "redline_failures",
    "redline_too_few_cases",
    "regressed",
    "not_measured",
    "baseline_missing",
]


@dataclass(frozen=True)
class Violation:
    metric: str
    kind: Kind
    value: float | None
    baseline: float | None
    n: int

    def describe(self) -> str:
        return (
            f"{self.metric}: {self.kind} (value {self.value}, baseline {self.baseline}, "
            f"{self.n} cases)"
        )


@dataclass(frozen=True)
class Verdict:
    key: tuple[str, str, str]
    has_baseline: bool
    violations: tuple[Violation, ...]


def redline_violations(metric: Metric, flags: Mapping[str, bool]) -> list[Violation]:
    n = len(flags)
    if not n:
        return [Violation(metric.name, "not_measured", None, None, 0)]
    failures = sum(flags.values())
    rate = round(failures / n, RATE_DIGITS)
    found: list[Violation] = []
    if failures:
        found.append(Violation(metric.name, "redline_failures", rate, None, n))
    if metric.min_cases is not None and n < metric.min_cases:
        found.append(Violation(metric.name, "redline_too_few_cases", rate, None, n))
    return found


def regressed(metric: Metric, gap: float, n: int) -> bool:
    return gap > (metric.tolerance or 0) + n * ROUNDING + EPSILON


def ratchet_violations(
    metric: Metric, current: Epoch, old: Epoch, failures: int, n: int
) -> list[Violation]:
    value, before = current.metrics.get(metric.name), old.metrics.get(metric.name)
    if value is None or before is None:
        return [Violation(metric.name, "baseline_missing", value, before, n)]
    gap = failures - before * n if metric.direction == "down" else before * n - failures
    if regressed(metric, gap, n):
        return [Violation(metric.name, "regressed", value, before, n)]
    return []


def metric_violations(
    metric: Metric, measured: Candidate, current: Epoch, old: Epoch | None
) -> list[Violation]:
    if metric.gate == "redline":
        return redline_violations(metric, measured.whole.get(metric.name, {}))
    flags = measured.failed.get(metric.name, {})
    value, n = measured.values.get(metric.name), len(flags)
    if value is None or not n:
        return [Violation(metric.name, "not_measured", value, None, n)]
    if old is None:
        return []
    return ratchet_violations(metric, current, old, sum(flags.values()), n)


def judge(measured: Candidate, baseline: Baseline, metrics: Sequence[Metric]) -> Verdict:
    current = Epoch(measured.backend_id, measured.rules_version, measured.mode, measured.values)
    old = baseline.epoch(*current.key)
    found = [
        item
        for metric in metrics
        if metric.gate != "record"
        for item in metric_violations(metric, measured, current, old)
    ]
    return Verdict(current.key, old is not None, tuple(found))
