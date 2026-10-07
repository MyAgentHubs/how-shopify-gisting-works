from dataclasses import dataclass
from pathlib import Path

from gisting.eval.guard_git import EMPTY_SNAPSHOT, change_between, genesis_gaps, git_bytes
from gisting.eval.guard_signature import GuardError
from gisting.eval.ratchet_audit_commit import commit_problems
from gisting.eval.ratchet_audit_history import History, history_findings, load_history
from gisting.eval.ratchet_audit_reports import Loader, ReportLoader
from gisting.eval.ratchet_audit_signature import signature_problem
from gisting.eval.ratchet_audit_tree import Finding, Tree, load_tree


@dataclass(frozen=True)
class AuditResult:
    anchor: str | None
    commits: int
    reports: int
    findings: tuple[Finding, ...]
    waivers: tuple[Finding, ...] = ()


def ensure_full_history(root: Path) -> None:
    shallow = git_bytes(root, "rev-parse", "--is-shallow-repository").decode().strip()
    if shallow != "false":
        message = "the history is shallow; the ratchet audit needs every commit (fetch-depth: 0)"
        raise GuardError(message)


def genesis_problem(root: Path, tree: Tree) -> str | None:
    try:
        change = change_between(root, EMPTY_SNAPSHOT, tree.snapshot)
        gaps = genesis_gaps(change.paths)
        if gaps:
            return f"the protected set does not cover {', '.join(gaps)}"
        problem = signature_problem(tree, tree, change)
    except GuardError as error:
        return str(error)
    if problem is None:
        return None
    return f"genesis hash {change.digest} is not signed by the anchor's own signers: {problem}"


def commit_findings(
    root: Path, loader: Loader, history: History, anchor: str
) -> tuple[list[Finding], int, list[Finding]]:
    previous = load_tree(root, anchor)
    problem = genesis_problem(root, previous)
    findings = [] if problem is None else [Finding(anchor, problem)]
    reports = ReportLoader(loader)
    waivers: list[Finding] = []
    judged = 0
    for commit in history.chain[history.chain.index(anchor) + 1 :]:
        current = load_tree(root, commit)
        done = commit_problems(reports, previous, current)
        findings += [Finding(commit, message) for message in done.problems]
        waivers += [Finding(commit, message) for message in done.waived]
        judged += done.reports
        previous = current
    return findings, judged, waivers


def audit(root: Path, loader: Loader, base: str | None = None) -> AuditResult:
    ensure_full_history(root)
    history = load_history(root)
    findings = history_findings(root, history, base)
    anchor = history.anchor
    if anchor is None:
        return AuditResult(None, 0, 0, tuple(findings))
    found, judged, waivers = commit_findings(root, loader, history, anchor)
    commits = len(history.chain) - history.chain.index(anchor) - 1
    return AuditResult(anchor, commits, judged, tuple(findings + found), tuple(waivers))
