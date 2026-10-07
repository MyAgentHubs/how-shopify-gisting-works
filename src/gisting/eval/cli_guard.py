import argparse
import shlex
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from gisting.eval.baseline_update import Candidate
from gisting.eval.cli_baseline import load_candidate
from gisting.eval.data import ROOT
from gisting.eval.guard_git import (
    EMPTY_SNAPSHOT,
    GuardChange,
    change_between,
    genesis_gaps,
    index_snapshot,
    tree_snapshot,
)
from gisting.eval.guard_preview import preview_lines
from gisting.eval.guard_signature import (
    NAMESPACE,
    SIGNATURE_DIR,
    GuardError,
    signature_file,
    signed_message,
)
from gisting.eval.ratchet_audit_reports import NewReports, ReportLoader, judge_commit_reports
from gisting.eval.ratchet_audit_tree import Tree
from gisting.eval.registry import Metric

MESSAGE_NAME = "gisting-guard-{prefix}.msg"
PREFIX_LENGTH = 12
KEY_FILE = "~/.ssh/gisting_signing"
FAILURE_EXIT = 1
NOT_NEEDED = "no protected paths changed; no signature needed\n"


def configure_guard_hash(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument(
        "--out",
        type=Path,
        help="where to write the message, default $TMPDIR/gisting-guard-<hash prefix>.msg",
    )
    parser.add_argument(
        "--genesis",
        action="store_true",
        help="hash every staged protected file against nothing, for the signature of the anchor",
    )
    parser.set_defaults(handler=handle_guard_hash)


def instructions(change: GuardChange, message: Path, preview: list[str]) -> str:
    quoted = shlex.quote(str(message))
    signature = shlex.quote(str(signature_file(Path(), change.digest)))
    directory = shlex.quote(SIGNATURE_DIR)
    lines = [
        f"guard hash: {change.digest}",
        f"parent tree: {change.parent_tree}",
        "protected paths changed:",
        *(f"  {path}" for path in change.paths),
        *preview,
        f"message written to: {message}",
        "run these two commands from the repository root:",
        f"ssh-keygen -Y sign -f {KEY_FILE} -n {NAMESPACE} {quoted}",
        f"mkdir -p {directory} && mv {shlex.quote(f'{message}.sig')} {signature}"
        f" && git add {signature}",
    ]
    return "".join(f"{line}\n" for line in lines)


def measuring(root: Path) -> ReportLoader:
    def measure(directory: Path, metrics: Sequence[Metric]) -> Candidate:
        return load_candidate(directory, root, list(metrics))

    return ReportLoader(measure)


def judged_reports(loader: ReportLoader, parent: Tree, new: Tree, genesis: bool) -> NewReports:
    if genesis:
        return NewReports([], [], [], [])
    return judge_commit_reports(loader, parent, new)


def staged_state(args: argparse.Namespace) -> tuple[GuardChange, list[str]]:
    root = args.root.resolve()
    parent = Tree(root, EMPTY_SNAPSHOT if args.genesis else tree_snapshot(root, "HEAD"))
    new = Tree(root, index_snapshot(root))
    loader = measuring(root)
    judged = judged_reports(loader, parent, new, args.genesis)
    change = change_between(root, parent.snapshot, new.snapshot, judged.waiver_paths)
    if args.genesis:
        gaps = genesis_gaps(change.paths)
        if gaps:
            message = f"the staged protected set does not cover {', '.join(gaps)}"
            raise GuardError(message)
    if not change.paths:
        return change, []
    return change, preview_lines(loader, parent, new, change, judged)


def handle_guard_hash(args: argparse.Namespace) -> int:
    try:
        change, preview = staged_state(args)
        if not change.paths:
            sys.stdout.write(NOT_NEEDED)
            return 0
        name = MESSAGE_NAME.format(prefix=change.digest[:PREFIX_LENGTH])
        message: Path = args.out or Path(tempfile.gettempdir()) / name
        message = message.absolute()
        message.write_bytes(signed_message(change.parent_tree, change.digest))
    except (GuardError, OSError) as error:
        sys.stderr.write(f"gisting.eval guard-hash: {error}\n")
        return FAILURE_EXIT
    sys.stdout.write(instructions(change, message, preview))
    return 0
