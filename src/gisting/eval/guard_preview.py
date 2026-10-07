from collections.abc import Mapping

from gisting.eval.baseline_diff import (
    Classification,
    NeedsSignature,
    Refresh,
    Tighten,
    ValueChange,
    classify,
    label,
    value_changes,
)
from gisting.eval.guard_git import GuardChange
from gisting.eval.ratchet_audit_reports import (
    BASELINE_FILE,
    METRICS_FILE,
    NewReports,
    ReportLoader,
    Unreadable,
    parse_baseline,
    parse_metrics,
    sources_of,
)
from gisting.eval.ratchet_audit_tree import Tree
from gisting.eval.registry import Metric

NOT_APPLICABLE = "baseline classification: not applicable, the anchor has no parent state"


def classification_name(result: Classification) -> str:
    if isinstance(result, Tighten | Refresh):
        return f"{type(result).__name__} (source report {result.report_dir})"
    return type(result).__name__


def value_line(change: ValueChange, registered: Mapping[str, Metric]) -> str:
    metric = registered.get(change.metric)
    note = "not registered" if metric is None else f"{metric.gate}, {metric.direction} is better"
    return f"  {label(change.key)} {change.metric}: {change.old} -> {change.new} ({note})"


def genesis_lines(new: Tree) -> list[str]:
    try:
        baseline = parse_baseline(new.read(BASELINE_FILE), "the staged state")
    except Unreadable as error:
        return [f"baseline values unavailable: {error}"]
    return [
        NOT_APPLICABLE,
        *(
            f"  {label(item.key)} {name} = {value}"
            for item in baseline.epochs
            for name, value in sorted(item.metrics.items())
        ),
    ]


def baseline_lines(
    loader: ReportLoader, parent: Tree, new: Tree, change: GuardChange
) -> tuple[list[str], bool]:
    try:
        old = parse_baseline(parent.read(BASELINE_FILE), "the parent commit")
        fresh = parse_baseline(new.read(BASELINE_FILE), "the staged state")
        old_metrics = parse_metrics(parent.read(METRICS_FILE), "the parent commit")
        metrics = parse_metrics(new.read(METRICS_FILE), "the staged state")
    except Unreadable as error:
        return [f"baseline classification unavailable: {error}"], False
    result = classify(old, fresh, old_metrics, metrics, sources_of(loader, new, metrics))
    registered = {item.name: item for item in metrics}
    reasons = result.reasons if isinstance(result, NeedsSignature) else ()
    lines = [f"baseline classification: {classification_name(result)}"]
    lines += [f"  reason: {reason}" for reason in reasons]
    lines += [value_line(item, registered) for item in value_changes(old, fresh)]
    return lines, not reasons and change.paths == (BASELINE_FILE,)


def waiver_lines(judged: NewReports) -> list[str]:
    lines = [f"cannot be waived: {item}" for item in judged.unreadable]
    for verdict in judged.verdicts:
        if verdict.unjudged:
            lines.append(f"cannot be waived: {verdict.unjudged}")
    waived = [verdict for verdict in judged.verdicts if verdict.violations]
    if waived:
        lines.append("reports that need a signed waiver:")
        lines += [f"  {message}" for verdict in waived for message in verdict.violations]
    return lines


def preview_lines(
    loader: ReportLoader,
    parent: Tree,
    new: Tree,
    change: GuardChange,
    judged: NewReports | None = None,
) -> list[str]:
    judged = judged or NewReports([], [], [], [])
    if BASELINE_FILE in parent.blobs:
        lines, exempt = baseline_lines(loader, parent, new, change)
    else:
        lines, exempt = genesis_lines(new), False
    waived = set(judged.waiver_paths)
    others = [path for path in change.paths if path != BASELINE_FILE and path not in waived]
    if others:
        lines.append(f"other protected files changed: {', '.join(others)}")
    lines += waiver_lines(judged)
    if exempt:
        lines.append("the audit passes a baseline-only change of this kind without a signature")
    return [*lines, f"signature required: {'no' if exempt else 'yes'}"]
