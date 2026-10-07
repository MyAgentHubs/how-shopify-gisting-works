import json
import re
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from gisting.eval.baseline import Baseline
from gisting.eval.baseline_diff import EpochKey, RejudgedReport, ReportsOf
from gisting.eval.baseline_update import Candidate
from gisting.eval.ratchet import judge
from gisting.eval.ratchet_audit_coverage import coverage_problems
from gisting.eval.ratchet_audit_tree import Tree
from gisting.eval.registry import Metric, parse_registry
from gisting.shopify.jsonvalue import Json

BASELINE_FILE = "eval/baseline.json"
METRICS_FILE = "eval/metrics.toml"
REPORTS_DIR = "eval/reports"
REPORT_FILE = "report.json"
REPORT_DEPTH = 5
TREE_SHA = re.compile(r"[0-9a-f]{40}")
FILE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")
MODES = ("full", "gist")
UNREADABLE = (ValueError, OSError, RecursionError)

Loader = Callable[[Path, Sequence[Metric]], Candidate]
CacheKey = tuple[str, tuple[str, ...], tuple[Metric, ...]]


class Unreadable(ValueError):
    pass


def parse_baseline(raw: bytes | None, where: str) -> Baseline:
    if raw is None:
        message = f"{where} has no {BASELINE_FILE}"
        raise Unreadable(message)
    try:
        return Baseline.parse(json.loads(raw))
    except UNREADABLE as error:
        message = f"{where}: {BASELINE_FILE} is unreadable: {error}"
        raise Unreadable(message) from error


def parse_metrics(raw: bytes | None, where: str) -> list[Metric]:
    if raw is None:
        message = f"{where} has no {METRICS_FILE}"
        raise Unreadable(message)
    try:
        metrics, problems = parse_registry(raw.decode("utf-8", errors="replace"))
    except RecursionError as error:
        message = f"{where}: {METRICS_FILE} is unreadable: {error}"
        raise Unreadable(message) from error
    if problems:
        message = f"{where}: {METRICS_FILE}: {problems[0]}"
        raise Unreadable(message)
    return metrics


def directory_of(name: str) -> str:
    return name.rpartition("/")[0]


def shaped_directory(directory: str) -> bool:
    parts = directory.split("/")
    return (
        len(parts) == REPORT_DEPTH - 1
        and f"{parts[0]}/{parts[1]}" == REPORTS_DIR
        and TREE_SHA.fullmatch(parts[2]) is not None
        and parts[3] in MODES
    )


def well_shaped(name: str) -> bool:
    directory, _, leaf = name.rpartition("/")
    return shaped_directory(directory) and FILE_NAME.fullmatch(leaf) is not None


def report_files(tree: Tree) -> dict[str, str]:
    return {name: blob for name, blob in tree.blobs.items() if name.startswith(f"{REPORTS_DIR}/")}


def report_directories(tree: Tree) -> list[str]:
    return sorted({directory_of(name) for name in report_files(tree) if well_shaped(name)})


def set_problems(parent: Tree, new: Tree) -> tuple[list[str], list[str]]:
    before, after = report_files(parent), report_files(new)
    problems = [f"report file {name} was deleted" for name in sorted(before.keys() - after.keys())]
    problems += [
        f"report file {name} was modified"
        for name in sorted(before.keys() & after.keys())
        if before[name] != after[name]
    ]
    known = {directory_of(name) for name in before}
    fresh: set[str] = set()
    for name in sorted(after.keys() - before.keys()):
        if not well_shaped(name):
            problems.append(f"{name} is not shaped like {REPORTS_DIR}/<tree>/<mode>/<file>")
        elif directory_of(name) in known:
            problems.append(f"file {name} was added to an existing report")
        else:
            fresh.add(directory_of(name))
    return problems, sorted(fresh)


@dataclass
class ReportLoader:
    load: Loader
    cache: dict[CacheKey, Candidate] = field(default_factory=dict[CacheKey, Candidate])

    def candidate(self, tree: Tree, directory: str, metrics: Sequence[Metric]) -> Candidate:
        names = tree.names_in(directory)
        key = (directory, tuple(tree.blobs[name] for name in names), tuple(metrics))
        if key not in self.cache:
            self.cache[key] = self.measure(tree, directory, names, metrics)
        return self.cache[key]

    def measure(
        self, tree: Tree, directory: str, names: Sequence[str], metrics: Sequence[Metric]
    ) -> Candidate:
        if not shaped_directory(directory):
            message = f"{directory} is not shaped like {REPORTS_DIR}/<tree>/<mode>"
            raise Unreadable(message)
        tree_sha, mode = directory.split("/")[2:]
        with tempfile.TemporaryDirectory(prefix="gisting-audit-") as scratch:
            target = Path(scratch) / tree_sha / mode
            target.mkdir(parents=True)
            for name in names:
                if not well_shaped(name):
                    message = f"{name} is not a report file name"
                    raise Unreadable(message)
                (target / name.rpartition("/")[2]).write_bytes(tree.blob_bytes(name))
            return self.load(target, metrics)


def declared_epoch(tree: Tree, directory: str) -> EpochKey | None:
    try:
        document: Json = json.loads(tree.read(f"{directory}/{REPORT_FILE}") or b"")
    except UNREADABLE:
        return None
    run = document.get("run") if isinstance(document, dict) else None
    if not isinstance(run, dict):
        return None
    backend, rules, mode = run.get("backend_id"), run.get("rules_version"), run.get("mode")
    if isinstance(backend, str) and isinstance(rules, str) and isinstance(mode, str):
        return backend, rules, mode
    return None


def sources_of(loader: ReportLoader, tree: Tree, metrics: Sequence[Metric]) -> ReportsOf:
    def lookup(key: EpochKey) -> list[RejudgedReport]:
        found: list[RejudgedReport] = []
        for directory in report_directories(tree):
            if declared_epoch(tree, directory) != key:
                continue
            try:
                measured = loader.candidate(tree, directory, metrics)
                uncovered = coverage_problems(tree, directory)
            except UNREADABLE:
                continue
            if uncovered:
                continue
            found.append(RejudgedReport(directory, measured.values))
        return found

    return lookup


@dataclass(frozen=True)
class ReportVerdict:
    directory: str
    files: tuple[str, ...]
    violations: tuple[str, ...]
    unjudged: str | None


def judge_one(
    loader: ReportLoader, new: Tree, directory: str, baseline: Baseline, metrics: Sequence[Metric]
) -> ReportVerdict:
    files = tuple(new.names_in(directory))
    try:
        measured = loader.candidate(new, directory, metrics)
        uncovered = coverage_problems(new, directory)
    except UNREADABLE as error:
        return ReportVerdict(directory, files, (), f"{directory} cannot be judged: {error}")
    verdict = judge(measured, baseline, metrics)
    judged = [item.describe() for item in verdict.violations]
    if not verdict.has_baseline:
        judged.append(f"epoch {verdict.key} has no baseline in the parent commit")
    return ReportVerdict(
        directory, files, tuple(f"{directory}: {m}" for m in [*judged, *uncovered]), None
    )


def judge_new_reports(
    loader: ReportLoader, parent: Tree, new: Tree, directories: Sequence[str]
) -> tuple[list[ReportVerdict], list[str]]:
    if not directories:
        return [], []
    try:
        baseline = parse_baseline(parent.read(BASELINE_FILE), "the parent commit")
        metrics = parse_metrics(parent.read(METRICS_FILE), "the parent commit")
    except Unreadable as error:
        return [], [f"cannot judge the new reports: {error}"]
    return [judge_one(loader, new, directory, baseline, metrics) for directory in directories], []


def waiver_paths(verdicts: Sequence[ReportVerdict]) -> tuple[str, ...]:
    return tuple(name for verdict in verdicts if verdict.violations for name in verdict.files)


@dataclass(frozen=True)
class NewReports:
    set_problems: list[str]
    fresh: list[str]
    verdicts: list[ReportVerdict]
    unreadable: list[str]

    @property
    def waiver_paths(self) -> tuple[str, ...]:
        return waiver_paths(self.verdicts)


def judge_commit_reports(loader: ReportLoader, parent: Tree, new: Tree) -> NewReports:
    sets, fresh = set_problems(parent, new)
    verdicts, unreadable = judge_new_reports(loader, parent, new, fresh)
    return NewReports(sets, fresh, verdicts, unreadable)
