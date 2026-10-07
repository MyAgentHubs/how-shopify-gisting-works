#!/usr/bin/env python3
import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

import guardlib
from guardlib import Violation

from gisting.eval.case_files import (
    CASE_SUFFIX,
    CASES_DIR,
    SEALED_DIR,
    SEALED_PLACEHOLDER,
    SEALED_SUFFIXES,
    load_cases,
)

MAIN_REFS = ("origin/main", "main")
SHORT_SHA = 8


def git(root: Path, *args: str) -> "subprocess.CompletedProcess[str]":
    command = ["git", "-C", str(root), *args]
    return subprocess.run(command, capture_output=True, text=True, check=False)


def resolve(root: Path, rev: str) -> str | None:
    result = git(root, "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}")
    return result.stdout.strip() if result.returncode == 0 else None


def default_base(root: Path) -> str | None:
    head = resolve(root, "HEAD")
    for ref in MAIN_REFS if head else ():
        tip = resolve(root, ref)
        if tip is None:
            continue
        if tip == head:
            return resolve(root, "HEAD~1") or head
        merged = git(root, "merge-base", "HEAD", ref)
        if merged.returncode == 0:
            return merged.stdout.strip()
    return None


def choose_base(root: Path, requested: str | None) -> str | None:
    if requested:
        found = resolve(root, requested)
        if found:
            return found
        sys.stderr.write(f"base {requested} not found, using the default base\n")
    return default_base(root)


def first_rewritten_line(old: str, new: str) -> int | None:
    old_lines = old.split("\n")
    kept = old_lines[:-1] if old.endswith("\n") else old_lines
    new_lines = new.split("\n")
    for number, line in enumerate(kept, start=1):
        if number > len(new_lines) or new_lines[number - 1] != line:
            return number
    return None


def base_case_files(root: Path, base: str) -> list[str]:
    listing = git(root, "ls-tree", "-r", "--name-only", "-z", base, "--", CASES_DIR)
    return [name for name in listing.stdout.split("\0") if name.endswith(CASE_SUFFIX)]


def append_only_violations(root: Path, base: str) -> list[Violation]:
    found: list[Violation] = []
    for name in base_case_files(root, base):
        current = root / name
        if not current.is_file():
            found.append(Violation(name, 1, f"file was deleted since {base[:SHORT_SHA]}"))
            continue
        old = git(root, "show", f"{base}:{name}").stdout
        line = first_rewritten_line(old, current.read_text(encoding="utf-8"))
        if line is not None:
            reason = f"line {line} was changed or removed since {base[:SHORT_SHA]}"
            found.append(Violation(name, line, reason))
    return found


def sealed_violations(root: Path) -> list[Violation]:
    sealed = root / SEALED_DIR
    names = sorted(path for path in sealed.rglob("*") if path.is_file()) if sealed.is_dir() else []
    return [
        Violation(path.relative_to(root).as_posix(), 1, "sealed cases must be encrypted")
        for path in names
        if path.name != SEALED_PLACEHOLDER and not path.name.endswith(SEALED_SUFFIXES)
    ]


def main(argv: Sequence[str] | None = None) -> int:
    parser = guardlib.make_parser("Fail when eval cases are malformed or rewritten.")
    parser.add_argument("--base", default=os.environ.get("GISTING_EVAL_CASES_BASE"))
    args = parser.parse_args(argv)
    root = args.root.resolve()
    _, problems = load_cases(root)
    found = [Violation(item.path, item.line, item.reason) for item in problems]
    found += sealed_violations(root)
    base = choose_base(root, args.base)
    if base is None:
        sys.stderr.write("no base revision, append-only check skipped\n")
    else:
        found += append_only_violations(root, base)
    return guardlib.report(found)


if __name__ == "__main__":
    sys.exit(main())
