#!/usr/bin/env python3
import ast
import re
import sys
from collections.abc import Iterator, Sequence
from pathlib import Path

import guardlib
from guardlib import Violation

SCAN_DIRS = ("src", "scripts", "apps")
EXAMPLE_NAME = ".env.example"
SYSTEM_VARIABLES = frozenset({
    "HOME",
    "PATH",
    "PWD",
    "OLDPWD",
    "USER",
    "SHELL",
    "TMPDIR",
    "LANG",
    "TERM",
    "IFS",
    "UID",
    "EUID",
    "PPID",
    "RANDOM",
    "HOSTNAME",
    "LINENO",
    "SECONDS",
    "REPLY",
    "OPTARG",
    "OPTIND",
    "PIPESTATUS",
    "BASH_SOURCE",
    "BASH_REMATCH",
    "FUNCNAME",
    "BASHPID",
    "NODE_ENV",
})
SHELL_REFERENCE = re.compile(r"\$\{?([A-Z][A-Z0-9_]*)")
TS_REFERENCE = re.compile(
    r"(?:process\.env|import\.meta\.env|\benv)(?:\.|\[['\"])([A-Z][A-Z0-9_]*)"
)
EXAMPLE_KEY = re.compile(r"(?:export\s+)?([A-Z][A-Z0-9_]*)=")
TS_SUFFIXES = (".ts", ".tsx", ".js", ".jsx", ".mjs")
Use = tuple[str, int]


def is_environ(node: ast.expr) -> bool:
    if isinstance(node, ast.Name):
        return node.id == "environ"
    return isinstance(node, ast.Attribute) and node.attr == "environ"


def is_getenv(node: ast.expr) -> bool:
    if isinstance(node, ast.Name):
        return node.id == "getenv"
    return isinstance(node, ast.Attribute) and node.attr == "getenv"


def literal(node: ast.expr | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def python_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Subscript) and is_environ(node.value):
        return literal(node.slice)
    if not isinstance(node, ast.Call) or not node.args:
        return None
    func = node.func
    environ_method = isinstance(func, ast.Attribute) and is_environ(func.value)
    if environ_method or is_getenv(func):
        return literal(node.args[0])
    return None


def python_uses(path: Path) -> Iterator[tuple[str, int]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.expr):
            name = python_name(node)
            if name is not None:
                yield name, node.lineno


def pattern_uses(path: Path, pattern: re.Pattern[str]) -> Iterator[tuple[str, int]]:
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    for number, line in enumerate(lines, start=1):
        for match in pattern.finditer(line):
            yield match.group(1), number


def file_uses(path: Path) -> Iterator[tuple[str, int]]:
    if path.suffix == ".py":
        found = python_uses(path)
    elif path.suffix == ".sh":
        found = pattern_uses(path, SHELL_REFERENCE)
    else:
        found = pattern_uses(path, TS_REFERENCE)
    return ((name, number) for name, number in found if name not in SYSTEM_VARIABLES)


def collect_uses(root: Path) -> dict[str, Use]:
    uses: dict[str, Use] = {}
    for path in guardlib.iter_files(root, (".py", ".sh", *TS_SUFFIXES), subdirs=SCAN_DIRS):
        relative = path.relative_to(root)
        if guardlib.is_test_file(relative):
            continue
        for name, number in file_uses(path):
            uses.setdefault(name, (relative.as_posix(), number))
    return uses


def example_keys(example: Path) -> dict[str, int]:
    keys: dict[str, int] = {}
    for number, line in enumerate(example.read_text(encoding="utf-8").splitlines(), start=1):
        match = EXAMPLE_KEY.match(line.strip())
        if match:
            keys.setdefault(match.group(1), number)
    return keys


def find_violations(root: Path) -> list[Violation]:
    example = root / EXAMPLE_NAME
    if not example.is_file():
        return [Violation(EXAMPLE_NAME, 1, "file is missing")]
    uses = collect_uses(root)
    keys = example_keys(example)
    found = [
        Violation(path, line, f"{name} is used but missing from {EXAMPLE_NAME}")
        for name, (path, line) in uses.items()
        if name not in keys
    ]
    found.extend(
        Violation(EXAMPLE_NAME, line, f"{name} is listed but never used")
        for name, line in keys.items()
        if name not in uses
    )
    return found


def main(argv: Sequence[str] | None = None) -> int:
    root = guardlib.parse_root("Compare used environment variables with .env.example.", argv)
    return guardlib.report(find_violations(root))


if __name__ == "__main__":
    sys.exit(main())
