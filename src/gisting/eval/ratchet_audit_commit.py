from collections.abc import Sequence
from dataclasses import dataclass

from gisting.eval.baseline_diff import NeedsSignature, classify
from gisting.eval.guard_git import GuardChange, change_between
from gisting.eval.guard_signature import GuardError
from gisting.eval.ratchet_audit_reports import (
    BASELINE_FILE,
    METRICS_FILE,
    ReportLoader,
    ReportVerdict,
    Unreadable,
    judge_commit_reports,
    parse_baseline,
    parse_metrics,
    sources_of,
)
from gisting.eval.ratchet_audit_signature import signature_problem
from gisting.eval.ratchet_audit_tree import Tree


def baseline_reasons(loader: ReportLoader, parent: Tree, new: Tree) -> list[str]:
    try:
        old = parse_baseline(parent.read(BASELINE_FILE), "the parent commit")
        fresh = parse_baseline(new.read(BASELINE_FILE), "this commit")
        metrics = parse_metrics(new.read(METRICS_FILE), "this commit")
    except Unreadable as error:
        return [str(error)]
    result = classify(old, fresh, metrics, metrics, sources_of(loader, new, metrics))
    return list(result.reasons) if isinstance(result, NeedsSignature) else []


def guard_problems(loader: ReportLoader, parent: Tree, new: Tree, change: GuardChange) -> list[str]:
    if not change.paths:
        return []
    reasons: list[str] = []
    if change.paths == (BASELINE_FILE,):
        reasons = baseline_reasons(loader, parent, new)
        if not reasons:
            return []
    problem = signature_problem(parent, new, change)
    if problem is None:
        return []
    paths = ", ".join(change.paths)
    head = f"protected paths changed ({paths}) and the guard hash {change.digest} is not signed"
    because = f" (no exemption: {'; '.join(reasons)})" if reasons else ""
    return [f"{head}: {problem}{because}"]


@dataclass(frozen=True)
class CommitResult:
    problems: list[str]
    reports: int
    waived: list[str]


def registry_problems(parent: Tree, new: Tree) -> list[str]:
    if new.blobs.get(METRICS_FILE) == parent.blobs.get(METRICS_FILE):
        return []
    try:
        parse_metrics(new.read(METRICS_FILE), "this commit")
    except Unreadable as error:
        return [str(error)]
    return []


def report_problems(verdicts: Sequence[ReportVerdict], signed: bool) -> list[str]:
    found = [verdict.unjudged for verdict in verdicts if verdict.unjudged]
    if not signed:
        found += [message for verdict in verdicts for message in verdict.violations]
    return found


def commit_problems(loader: ReportLoader, parent: Tree, new: Tree) -> CommitResult:
    judged = judge_commit_reports(loader, parent, new)
    verdicts, extra = judged.verdicts, judged.waiver_paths
    try:
        change = change_between(parent.root, parent.snapshot, new.snapshot, extra)
        found = guard_problems(loader, parent, new, change)
    except (GuardError, RecursionError) as error:
        found = [f"the guard check failed: {error}"]
    signed = bool(extra) and not found
    waived = [message for verdict in verdicts for message in verdict.violations]
    found += registry_problems(parent, new) + judged.set_problems + judged.unreadable
    found += report_problems(verdicts, signed)
    return CommitResult(found, len(judged.fresh), waived if signed else [])
