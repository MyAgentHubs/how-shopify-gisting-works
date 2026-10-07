import os
import re
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path

REPORTS_DIR = "eval/reports"
TREE_SHA = re.compile(r"[0-9a-f]{40}")
DIFFERS = 1


class GitError(RuntimeError):
    pass


def run_git(
    root: Path, *args: str, env: Mapping[str, str] | None = None
) -> "subprocess.CompletedProcess[str]":
    try:
        return subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            env=dict(os.environ if env is None else env),
            check=False,
        )
    except OSError as error:
        message = f"cannot run git: {error}"
        raise GitError(message) from error


def git(root: Path, *args: str, env: Mapping[str, str] | None = None) -> str:
    done = run_git(root, *args, env=env)
    if done.returncode:
        message = f"git {args[0]} failed: {done.stderr.strip()[-200:]}"
        raise GitError(message)
    return done.stdout


def code_tree_sha(root: Path) -> str:
    with tempfile.TemporaryDirectory(prefix="gisting-eval-index-") as scratch:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(scratch) / "index")}
        git(root, "read-tree", "HEAD", env=env)
        git(root, "rm", "--cached", "-r", "-q", "--ignore-unmatch", "--", REPORTS_DIR, env=env)
        return git(root, "write-tree", env=env).strip()


def dirty_paths(root: Path) -> list[str]:
    listing = git(root, "status", "--porcelain", "-z", "--", ".", f":(exclude){REPORTS_DIR}")
    return [entry[3:] for entry in listing.split("\0") if entry]


def paths_differ(root: Path, tree: str, paths: Sequence[str]) -> bool:
    if not TREE_SHA.fullmatch(tree):
        message = "a tree must be a full 40-hex sha"
        raise GitError(message)
    done = run_git(root, "diff", "--quiet", tree, "HEAD", "--", *paths)
    if done.returncode in (0, DIFFERS):
        return done.returncode == DIFFERS
    message = f"git diff failed: {done.stderr.strip()[-200:]}"
    raise GitError(message)
