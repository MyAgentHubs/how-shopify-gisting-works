import argparse
import json
import sys
from pathlib import Path

from gisting.eval.baseline import Baseline, Epoch, load_baseline, parse_mode
from gisting.eval.baseline_update import (
    RATE_DIGITS,
    Candidate,
    Change,
    UpdateRefused,
    decide,
    dump_baseline,
    with_epoch,
)
from gisting.eval.case import FINAL
from gisting.eval.cli_grade import REPORT_FILE
from gisting.eval.data import ROOT
from gisting.eval.dataclass_json import DecodeError
from gisting.eval.judging import Judges
from gisting.eval.registry import Metric, load_registry
from gisting.eval.report import (
    Graded,
    ReportError,
    case_map,
    grade_rows,
    load_rows,
    require_complete,
    sha256_text,
)
from gisting.eval.report_identity import require_identity
from gisting.eval.report_tokens import as_object, token_metrics
from gisting.eval.runner import TRANSCRIPTS_FILE
from gisting.eval.tree import GitError, dirty_paths
from gisting.shopify.jsonvalue import Json, JsonObject

BASELINE_FILE = "eval/baseline.json"
METRICS_FILE = "eval/metrics.toml"
USAGE_EXIT = 2
GATED = ("redline", "ratchet")


def configure_baseline_update(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--after", type=Path, required=True, help="report directory of the new run")
    parser.add_argument(
        "--before", type=Path, help="report directory of the run behind the baseline"
    )
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.set_defaults(handler=handle_baseline_update)


def stored_report(directory: Path, text: str) -> JsonObject:
    document: Json = json.loads((directory / REPORT_FILE).read_text(encoding="utf-8"))
    cases = as_object(as_object(document).get("cases"))
    if cases.get("transcripts_sha256") != sha256_text(text):
        message = f"{directory}: report.json does not belong to its transcripts"
        raise ReportError(message)
    return as_object(document)


def final_outcomes(dev: list[Graded], name: str) -> dict[str, bool]:
    return {g.case.id: g.outcomes[name, FINAL].failed for g in dev if (name, FINAL) in g.outcomes}


def dev_values(dev: list[Graded], metrics: list[Metric], mode: str) -> dict[str, float | None]:
    tokens = token_metrics([item.row for item in dev], mode)
    values: dict[str, float | None] = {}
    for metric in metrics:
        flags = final_outcomes(dev, metric.name)
        recorded = tokens.get(metric.name)
        if metric.gate in GATED and flags:
            values[metric.name] = round(sum(flags.values()) / len(flags), RATE_DIGITS)
        elif metric.gate not in GATED and isinstance(recorded, (int, float)):
            values[metric.name] = float(recorded)
    return values


def load_candidate(directory: Path, root: Path, metrics: list[Metric]) -> Candidate:
    path = directory / TRANSCRIPTS_FILE
    report = stored_report(directory, path.read_text(encoding="utf-8"))
    rows = load_rows(path)
    require_identity(directory, report, rows)
    run = as_object(report.get("run"))
    backend, rules, mode = (
        run.get("backend_id"),
        run.get("rules_version"),
        parse_mode(run.get("mode")),
    )
    if not isinstance(backend, str) or not isinstance(rules, str) or mode is None:
        message = f"{directory}: report.json names no backend, rules version or mode"
        raise ReportError(message)
    graded, errors = grade_rows(rows, case_map(root), Judges(root))
    require_complete(report, rows, graded, errors)
    dev = [item for item in graded if item.case.split == "dev"]
    if not dev:
        message = f"{directory}: the run has no dev cases"
        raise ReportError(message)
    failed = {metric.name: final_outcomes(dev, metric.name) for metric in metrics}
    whole = {metric.name: final_outcomes(graded, metric.name) for metric in metrics}
    return Candidate(backend, rules, mode, dev_values(dev, metrics, mode), failed, whole)


def describe(change: Change) -> str:
    return f"{change.metric}: {change.action} {change.old} -> {change.new} {change.detail}".rstrip()


def update(args: argparse.Namespace) -> list[Change]:
    root = args.root.resolve()
    other = [path for path in dirty_paths(root) if path != BASELINE_FILE]
    if other:
        message = f"commit the baseline on its own; {len(other)} other uncommitted paths"
        raise ReportError(message)
    metrics, problems = load_registry(root / METRICS_FILE)
    if problems:
        message = f"{METRICS_FILE}: {problems[0]}"
        raise ReportError(message)
    baseline: Baseline = load_baseline(root / BASELINE_FILE)
    after = load_candidate(args.after, root, metrics)
    before = load_candidate(args.before, root, metrics) if args.before else None
    old = baseline.epoch(after.backend_id, after.rules_version, after.mode)
    values, changes = decide(old, after, before, metrics)
    epoch = Epoch(after.backend_id, after.rules_version, after.mode, values)
    (root / BASELINE_FILE).write_text(dump_baseline(with_epoch(baseline, epoch)), encoding="utf-8")
    return changes


def handle_baseline_update(args: argparse.Namespace) -> int:
    try:
        changes = update(args)
    except (UpdateRefused, ReportError, GitError, DecodeError, ValueError, OSError) as error:
        sys.stderr.write(f"gisting.eval baseline-update: {error}\n")
        return USAGE_EXIT
    sys.stdout.write("".join(describe(change) + "\n" for change in changes))
    return 0
