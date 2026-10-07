import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

from gisting.eval.applicability import REASON, partition_applicable, production_tools
from gisting.eval.case_files import load_cases
from gisting.eval.data import ROOT
from gisting.eval.runner import (
    MODES,
    Launcher,
    RunFailed,
    RunResult,
    RunSpec,
    Selection,
    run_cases,
    select_cases,
    subprocess_launcher,
)
from gisting.eval.slots import SlotError

USAGE_EXIT = 2
FAILURE_EXIT = 1
RUN_SPLITS = ("train", "dev")
RED_LINES = ("1", "2", "3", "4", "none")


def add_selection_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--split", action="append", choices=RUN_SPLITS, dest="splits")
    parser.add_argument("--red-line", action="append", choices=RED_LINES, dest="red_lines")
    parser.add_argument("--family", action="append", dest="families")
    parser.add_argument("--per-red-line", type=int, help="take only the first N cases of each")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--env-file", type=Path)


def selection_of(args: argparse.Namespace) -> Selection:
    return Selection(
        tuple(args.splits or ("dev",)),
        tuple(args.red_lines or ()),
        tuple(args.families or ()),
        args.per_red_line,
    )


def configure_run(parser: argparse.ArgumentParser) -> None:
    add_selection_arguments(parser)
    parser.add_argument("--mode", choices=MODES, required=True, help="gist reads GISTING_GIST_DIR")
    parser.add_argument("--out", type=Path, required=True)
    parser.set_defaults(handler=handle_run)


def run_selection(
    args: argparse.Namespace, root: Path, mode: str, out: Path, launch: Launcher
) -> RunResult:
    loaded, problems = load_cases(root)
    if problems:
        message = f"{len(problems)} case file problems; run scripts/check_eval_cases.py"
        raise RunFailed(message)
    selection = selection_of(args)
    kept, skipped = partition_applicable(loaded, production_tools(root))
    cases = select_cases(kept, selection)
    if not cases:
        message = "no cases match the selection"
        raise RunFailed(message)
    wanted = select_cases(skipped, replace(selection, per_red_line=None))
    ids = tuple(sorted(case.id for case in wanted))
    spec = RunSpec(root, mode, out, launch, env_file=args.env_file, not_applicable=ids)
    return run_cases(spec, cases)


def handle_run(args: argparse.Namespace, launch: Launcher = subprocess_launcher) -> int:
    try:
        result = run_selection(args, args.root.resolve(), args.mode, args.out, launch)
    except (RunFailed, SlotError, OSError) as error:
        sys.stderr.write(f"gisting.eval run: {error}\n")
        return USAGE_EXIT
    summary = {
        "cases": result.cases,
        "errors": result.errors,
        "unknown_emails": result.unknown_emails,
        "transcripts": str(result.path),
        "not_applicable": {
            "count": len(result.not_applicable),
            "reason": REASON if result.not_applicable else None,
            "case_ids": list(result.not_applicable),
        },
    }
    sys.stdout.write(json.dumps(summary, sort_keys=True) + "\n")
    return FAILURE_EXIT if result.errors else 0
