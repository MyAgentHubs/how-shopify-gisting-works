import argparse
import json
import sys
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from gisting.eval.case_build import TemplateError, build_cases
from gisting.eval.case_files import CASE_SUFFIX
from gisting.eval.case_spec import EvalCase
from gisting.eval.cli_baseline import configure_baseline_update
from gisting.eval.cli_evaluate import configure_evaluate
from gisting.eval.cli_grade import configure_grade
from gisting.eval.cli_guard import configure_guard_hash
from gisting.eval.cli_run import configure_run

USAGE_EXIT = 2
FAILURE_EXIT = 1
RED_LINES = (1, 3, 4)
ROOT = Path(__file__).resolve().parents[3]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gisting.eval")
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build-cases", help="write eval cases built from template data")
    build.add_argument("--red-line", type=int, choices=RED_LINES, required=True)
    build.add_argument("--root", type=Path, default=ROOT)
    build.add_argument("--out", type=Path, help="directory holding <split>/<family>.jsonl")
    build.set_defaults(handler=handle_build)
    configure_run(commands.add_parser("run", help="run eval cases and write transcripts"))
    configure_grade(commands.add_parser("grade", help="grade transcripts into report.json"))
    configure_baseline_update(
        commands.add_parser("baseline-update", help="tighten eval/baseline.json on dev")
    )
    configure_evaluate(
        commands.add_parser("evaluate", help="run and grade every mode into eval/reports")
    )
    configure_guard_hash(
        commands.add_parser("guard-hash", help="print the guard hash of staged protected changes")
    )
    return parser


def to_line(case: EvalCase) -> str:
    return json.dumps(asdict(case), ensure_ascii=False) + "\n"


def write_files(out: Path, cases: Sequence[EvalCase]) -> None:
    lines: dict[Path, list[str]] = defaultdict(list)
    for case in cases:
        lines[out / case.split / f"{case.family}{CASE_SUFFIX}"].append(to_line(case))
    for path, body in lines.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(body), encoding="utf-8")


def handle_build(args: argparse.Namespace) -> int:
    try:
        cases = build_cases(args.root.resolve(), args.red_line)
    except TemplateError as error:
        sys.stderr.write(f"build-cases: {error}\n")
        return FAILURE_EXIT
    if args.out is None:
        sys.stdout.write("".join(to_line(case) for case in cases))
    else:
        write_files(args.out, cases)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.handler(args))
