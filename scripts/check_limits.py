#!/usr/bin/env python3
import ast
import sys
from collections.abc import Sequence
from pathlib import Path

import guardlib
from guardlib import Violation

MAX_FILE_LINES = 300
MAX_FUNCTION_LINES = 50
SUFFIXES = (".py", ".ts", ".tsx", ".mjs")
FunctionNode = ast.FunctionDef | ast.AsyncFunctionDef


def function_violations(root: Path, path: Path, text: str) -> list[Violation]:
    relative = guardlib.rel(root, path)
    try:
        tree = ast.parse(text)
    except SyntaxError as error:
        return [Violation(relative, error.lineno or 1, f"syntax error: {error.msg}")]
    lines = text.splitlines()
    found: list[Violation] = []
    for node in ast.walk(tree):
        if isinstance(node, FunctionNode) and node.end_lineno is not None:
            body = "\n".join(lines[node.lineno - 1 : node.end_lineno])
            size = guardlib.non_blank_lines(body)
            if size > MAX_FUNCTION_LINES:
                reason = f"function {node.name} has {size} non-blank lines"
                found.append(Violation(relative, node.lineno, reason))
    return found


def file_violations(root: Path, path: Path) -> list[Violation]:
    relative = path.relative_to(root)
    text = path.read_text(encoding="utf-8")
    size = guardlib.non_blank_lines(text)
    found: list[Violation] = []
    if size > MAX_FILE_LINES:
        reason = f"file has {size} non-blank lines (max {MAX_FILE_LINES})"
        found.append(Violation(relative.as_posix(), 1, reason))
    if path.suffix == ".py" and not guardlib.is_test_file(relative):
        found.extend(function_violations(root, path, text))
    return found


def find_violations(root: Path) -> list[Violation]:
    found: list[Violation] = []
    for path in guardlib.iter_files(root, SUFFIXES):
        found.extend(file_violations(root, path))
    return found


def main(argv: Sequence[str] | None = None) -> int:
    root = guardlib.parse_root("Enforce file and function size limits.", argv)
    return guardlib.report(find_violations(root))


if __name__ == "__main__":
    sys.exit(main())
