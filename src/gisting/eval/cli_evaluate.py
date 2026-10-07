import argparse
import os
import sys
from pathlib import Path

from gisting.eval.cli_grade import grade_directory, summary_lines
from gisting.eval.cli_run import add_selection_arguments, run_selection
from gisting.eval.report import ReportError
from gisting.eval.runner import MODES, TRANSCRIPTS_FILE, Launcher, RunFailed, subprocess_launcher
from gisting.eval.slots import SlotError
from gisting.eval.tree import REPORTS_DIR, GitError, code_tree_sha, dirty_paths

USAGE_EXIT = 2
INCOMPLETE_EXIT = 1
GIST_DIR_VARIABLE = "GISTING_GIST_DIR"
SHOWN_PATHS = 5


def configure_evaluate(parser: argparse.ArgumentParser) -> None:
    add_selection_arguments(parser)
    parser.add_argument("--mode", action="append", choices=MODES, dest="modes")
    parser.set_defaults(handler=handle_evaluate)


def preflight(args: argparse.Namespace, root: Path, modes: tuple[str, ...]) -> str:
    dirty = dirty_paths(root)
    if dirty:
        shown = ", ".join(dirty[:SHOWN_PATHS])
        message = f"{len(dirty)} uncommitted paths (commit or discard them first): {shown}"
        raise RunFailed(message)
    if "gist" in modes and not os.environ.get(GIST_DIR_VARIABLE):
        message = f"{GIST_DIR_VARIABLE} must point at a Gist artifact for --mode gist"
        raise RunFailed(message)
    sha = code_tree_sha(root)
    for mode in modes:
        if (root / REPORTS_DIR / sha / mode / TRANSCRIPTS_FILE).exists():
            message = f"{REPORTS_DIR}/{sha}/{mode} already exists; delete it to run again"
            raise RunFailed(message)
    return sha


def evaluate(args: argparse.Namespace, launch: Launcher) -> int:
    root = args.root.resolve()
    modes = tuple(args.modes or MODES)
    sha = preflight(args, root, modes)
    incomplete = False
    for mode in modes:
        out = root / REPORTS_DIR / sha / mode
        result = run_selection(args, root, mode, out, launch)
        report = grade_directory(out, root, sha)
        sys.stdout.write("".join(f"{mode}: {line}\n" for line in summary_lines(report)))
        incomplete = incomplete or result.errors > 0
    return INCOMPLETE_EXIT if incomplete else 0


def handle_evaluate(args: argparse.Namespace, launch: Launcher = subprocess_launcher) -> int:
    try:
        return evaluate(args, launch)
    except (RunFailed, SlotError, ReportError, GitError, ValueError, OSError) as error:
        sys.stderr.write(f"gisting.eval evaluate: {error}\n")
        return USAGE_EXIT
