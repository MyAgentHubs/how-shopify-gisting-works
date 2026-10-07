import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from gisting.eval.guard_signature import (
    EMPTY_TREE,
    TOOL_ENV,
    File,
    GuardError,
    changed_paths,
    diff_hash,
    parse_patterns,
    path_problems,
    protected_names,
    system_tool,
)

GUARD_FILE = "data/eval/guard.json"
GENESIS_FILE = "eval/genesis.json"
GENESIS_REQUIRED = (
    GENESIS_FILE,
    GUARD_FILE,
    ".github/allowed_signers",
    "eval/baseline.json",
    "eval/metrics.toml",
)
ERROR_TAIL = 200
ODD_PATHS_SHOWN = 5


@dataclass(frozen=True)
class GuardChange:
    digest: str
    paths: tuple[str, ...]
    parent_tree: str


@dataclass(frozen=True)
class Snapshot:
    tree: str
    blobs: dict[str, str]
    modes: dict[str, str]


EMPTY_SNAPSHOT = Snapshot(EMPTY_TREE, {}, {})


def git_bytes(root: Path, *args: str, stdin: bytes | None = None) -> bytes:
    command = [system_tool("git"), "-C", str(root), *args]
    try:
        done = subprocess.run(command, input=stdin, capture_output=True, check=False, env=TOOL_ENV)
    except OSError as error:
        message = f"cannot run git: {error}"
        raise GuardError(message) from error
    if done.returncode:
        detail = done.stderr.decode(errors="replace").strip()[-ERROR_TAIL:]
        message = f"git {args[0]} failed: {detail}"
        raise GuardError(message)
    return done.stdout


def entries(listing: bytes) -> list[tuple[list[str], str]]:
    rows: list[tuple[list[str], str]] = []
    for entry in listing.decode(errors="surrogateescape").split("\0"):
        if entry:
            meta, _, path = entry.partition("\t")
            rows.append((meta.split(" "), path))
    return rows


def tree_snapshot(root: Path, rev: str) -> Snapshot:
    if rev.startswith("-"):
        message = f"git revision {rev!r} looks like an option"
        raise GuardError(message)
    tree = git_bytes(root, "rev-parse", "--verify", f"{rev}^{{tree}}").decode().strip()
    rows = [
        (path, fields)
        for fields, path in entries(git_bytes(root, "ls-tree", "-r", "-z", tree))
        if fields[1] == "blob"
    ]
    return Snapshot(
        tree,
        {path: fields[2] for path, fields in rows},
        {path: fields[0] for path, fields in rows},
    )


def index_snapshot(root: Path) -> Snapshot:
    return tree_snapshot(root, git_bytes(root, "write-tree").decode().strip())


def guard_patterns(root: Path, parent: Snapshot, new: Snapshot) -> tuple[str, ...]:
    documents = [
        git_bytes(root, "cat-file", "blob", snapshot.blobs[GUARD_FILE])
        for snapshot in (parent, new)
        if GUARD_FILE in snapshot.blobs
    ]
    if not documents:
        message = f"neither side has {GUARD_FILE}; guard.json is required"
        raise GuardError(message)
    return tuple(sorted({pattern for blob in documents for pattern in parse_patterns(blob)}))


def entry_of(snapshot: Snapshot, name: str) -> tuple[str | None, str | None]:
    return snapshot.modes.get(name), snapshot.blobs.get(name)


def change_between(
    root: Path, parent: Snapshot, new: Snapshot, extra: Sequence[str] = ()
) -> GuardChange:
    patterns = tuple(sorted({*guard_patterns(root, parent, new), *extra}))
    problems = path_problems(patterns, [*parent.blobs, *new.blobs])
    if problems:
        message = f"odd paths in the trees: {'; '.join(problems[:ODD_PATHS_SHOWN])}"
        raise GuardError(message)
    names = protected_names(patterns, [*parent.blobs, *new.blobs])
    moved = [name for name in names if entry_of(parent, name) != entry_of(new, name)]

    def side(snapshot: Snapshot) -> dict[str, File | None]:
        return {
            name: File(snapshot.modes[name], git_bytes(root, "cat-file", "blob", blob))
            if (blob := snapshot.blobs.get(name))
            else None
            for name in moved
        }

    before, after = side(parent), side(new)
    return GuardChange(
        diff_hash(patterns, before, after),
        tuple(changed_paths(patterns, before, after)),
        parent.tree,
    )


def staged_change(root: Path) -> GuardChange:
    return change_between(root, tree_snapshot(root, "HEAD"), index_snapshot(root))


def staged_genesis_change(root: Path) -> GuardChange:
    return change_between(root, EMPTY_SNAPSHOT, index_snapshot(root))


def genesis_gaps(paths: tuple[str, ...]) -> list[str]:
    return [name for name in GENESIS_REQUIRED if name not in paths]
