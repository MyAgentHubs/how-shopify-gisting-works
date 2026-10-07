import argparse
import json
import sys
from pathlib import Path

from gisting.eval.applicability import read_record
from gisting.eval.data import ROOT
from gisting.eval.report import (
    ReportError,
    build_report,
    case_map,
    load_rows,
    with_not_applicable,
)
from gisting.eval.runner import TRANSCRIPTS_FILE
from gisting.eval.tree import GitError, code_tree_sha
from gisting.shopify.jsonvalue import JsonObject

REPORT_FILE = "report.json"
USAGE_EXIT = 2
INCOMPLETE_EXIT = 1
JSON_INDENT = 2


def configure_grade(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--dir", type=Path, required=True, help="holds transcripts.jsonl")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--code-tree-sha", help="default: the tree of HEAD without eval/reports")
    parser.set_defaults(handler=handle_grade)


def dump_report(report: JsonObject) -> str:
    return json.dumps(report, indent=JSON_INDENT, sort_keys=True, ensure_ascii=False) + "\n"


def grade_directory(directory: Path, root: Path, tree_sha: str | None) -> JsonObject:
    path = directory / TRANSCRIPTS_FILE
    if not path.is_file():
        message = f"{path} not found"
        raise ReportError(message)
    cases = case_map(root)
    sha = tree_sha or code_tree_sha(root)
    text = path.read_text(encoding="utf-8")
    rows = load_rows(path)
    report = build_report(rows, cases, root, sha, text)
    report = with_not_applicable(report, read_record(directory), rows, cases)
    (directory / REPORT_FILE).write_text(dump_report(report), encoding="utf-8")
    return report


def not_applicable_line(report: JsonObject) -> list[str]:
    cases = report.get("cases")
    section = cases.get("not_applicable") if isinstance(cases, dict) else None
    if not isinstance(section, dict) or not section.get("count"):
        return []
    return [f"not applicable: {section['count']} ({section['reason']})"]


def summary_lines(report: JsonObject) -> list[str]:
    lines: list[str] = []
    metrics = report.get("metrics")
    for name, entry in metrics.items() if isinstance(metrics, dict) else ():
        layers = entry.get("layers") if isinstance(entry, dict) else None
        for layer, counts in layers.items() if isinstance(layers, dict) else ():
            if isinstance(counts, dict):
                lines.append(
                    f"{name} {layer}: {counts['failures']} / {counts['n']}"
                    f" (95% upper bound {counts['upper95']})"
                )
    return [*lines, *not_applicable_line(report)]


def handle_grade(args: argparse.Namespace) -> int:
    try:
        report = grade_directory(args.dir, args.root.resolve(), args.code_tree_sha)
    except (ReportError, GitError, ValueError, OSError) as error:
        sys.stderr.write(f"gisting.eval grade: {error}\n")
        return USAGE_EXIT
    sys.stdout.write("".join(line + "\n" for line in summary_lines(report)))
    cases = report["cases"]
    complete = isinstance(cases, dict) and cases.get("complete") is True
    return 0 if complete else INCOMPLETE_EXIT
