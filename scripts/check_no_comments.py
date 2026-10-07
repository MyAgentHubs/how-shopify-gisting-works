#!/usr/bin/env python3
import ast
import io
import re
import sys
import tokenize
from collections.abc import Iterator, Sequence
from pathlib import Path

import guardlib
from guardlib import Violation
from ts_comments import TsComment, ts_comments

CODE = r"[A-Z]{1,5}[0-9]{1,4}"
PYTHON_DIRECTIVES = (
    re.compile(rf"# noqa: {CODE}(, {CODE})*"),
    re.compile(r"# type: ignore\[[a-z-]+(, [a-z-]+)*\]"),
    re.compile(r"# pyright: ignore\[[A-Za-z]+(, [A-Za-z]+)*\]"),
)
SEE_POINTER = re.compile(r"# see: (docs/decisions/[0-9]{4}-[a-z0-9-]+\.md)")
SHELL_DIRECTIVE = re.compile(r"# shellcheck disable=SC[0-9]{4}(,SC[0-9]{4})*")
HEREDOC = re.compile(r"(?<!<)<<(?!<)-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
SHELL_WORD_BREAKS = " \t;|&("
TS_DISABLE_NEXT_LINE = re.compile(r"// eslint-disable-next-line [@a-z0-9/-]+(, [@a-z0-9/-]+)*")
TS_EXPECT_ERROR = "// @ts-expect-error"
TS_SUFFIXES = (".ts", ".tsx", ".mjs")


def python_comment_problem(root: Path, text: str, line_number: int) -> str | None:
    if line_number == 1 and text.startswith("#!"):
        return None
    if any(pattern.fullmatch(text) for pattern in PYTHON_DIRECTIVES):
        return None
    pointer = SEE_POINTER.fullmatch(text)
    if pointer is None:
        return f"comment is not an allowed directive: {text}"
    if not (root / pointer.group(1)).is_file():
        return f"see pointer target does not exist: {pointer.group(1)}"
    return None


def python_comments(source: str) -> Iterator[tuple[int, str]]:
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.COMMENT:
            yield token.start[0], token.string


def string_statements(tree: ast.AST) -> Iterator[ast.Expr]:
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            yield node


def docstring_lines(tree: ast.AST) -> Iterator[tuple[int, str]]:
    owners = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    claimed: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, owners) and ast.get_docstring(node, clean=False) is not None:
            claimed.add(node.body[0].lineno)
            yield node.body[0].lineno, "docstring is not allowed"
    for statement in string_statements(tree):
        if statement.lineno not in claimed:
            yield statement.lineno, "bare string statement is not allowed"


def check_python(root: Path, path: Path) -> tuple[list[Violation], int]:
    relative = guardlib.rel(root, path)
    source = path.read_text(encoding="utf-8")
    found: list[Violation] = []
    directives = 0
    for line_number, text in python_comments(source):
        problem = python_comment_problem(root, text, line_number)
        if problem is None:
            directives += 0 if text.startswith("#!") else 1
        else:
            found.append(Violation(relative, line_number, problem))
    try:
        tree = ast.parse(source)
    except SyntaxError as error:
        found.append(Violation(relative, error.lineno or 1, f"syntax error: {error.msg}"))
        return found, directives
    found.extend(Violation(relative, line, reason) for line, reason in docstring_lines(tree))
    return found, directives


def ts_comment_allowed(comment: TsComment, is_test: bool) -> bool:
    if comment.is_block or not comment.whole_line:
        return False
    if TS_DISABLE_NEXT_LINE.fullmatch(comment.text):
        return True
    return is_test and comment.text == TS_EXPECT_ERROR


def check_ts(root: Path, path: Path) -> tuple[list[Violation], int]:
    relative = guardlib.rel(root, path)
    is_test = guardlib.is_test_file(path.relative_to(root))
    source = path.read_text(encoding="utf-8")
    found: list[Violation] = []
    directives = 0
    for comment in ts_comments(source):
        if ts_comment_allowed(comment, is_test):
            directives += 1
        else:
            found.append(Violation(relative, comment.line, "comment is not an allowed directive"))
    return found, directives


def shell_comment_start(line: str) -> int | None:
    quote = ""
    index = 0
    while index < len(line):
        char = line[index]
        if char == "\\" and quote != "'":
            index += 2
            continue
        if quote:
            quote = "" if char == quote else quote
        elif char in "'\"":
            quote = char
        elif char == "#" and (index == 0 or line[index - 1] in SHELL_WORD_BREAKS):
            return index
        index += 1
    return None


def check_shell(root: Path, path: Path) -> tuple[list[Violation], int]:
    relative = guardlib.rel(root, path)
    found: list[Violation] = []
    directives = 0
    terminator: str | None = None
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if terminator is not None:
            terminator = None if line.strip() == terminator else terminator
            continue
        start = shell_comment_start(line)
        if start is None:
            heredoc = HEREDOC.search(line)
            terminator = heredoc.group(2) if heredoc else None
        elif number == 1 and line.startswith("#!"):
            continue
        elif not line[:start].strip() and SHELL_DIRECTIVE.fullmatch(line.strip()):
            directives += 1
        else:
            found.append(Violation(relative, number, f"comment is not allowed: {line[start:]}"))
    return found, directives


def shell_files(root: Path) -> Iterator[Path]:
    yield from guardlib.iter_files(root, (".sh",), subdirs=("scripts",))
    yield from guardlib.iter_files(root, ("",), subdirs=(".githooks",))


def scan(root: Path) -> tuple[list[Violation], int]:
    found: list[Violation] = []
    total = 0
    for path in guardlib.iter_files(root, (".py",)):
        violations, count = check_python(root, path)
        found.extend(violations)
        total += count
    for path in guardlib.iter_files(root, TS_SUFFIXES):
        violations, count = check_ts(root, path)
        found.extend(violations)
        total += count
    for path in shell_files(root):
        violations, count = check_shell(root, path)
        found.extend(violations)
        total += count
    return found, total


def main(argv: Sequence[str] | None = None) -> int:
    parser = guardlib.make_parser("Forbid comments and docstrings except directives.")
    parser.add_argument("--count", action="store_true")
    args = parser.parse_args(argv)
    found, total = scan(args.root.resolve())
    if args.count:
        sys.stdout.write(f"{total}\n")
    return guardlib.report(found)


if __name__ == "__main__":
    sys.exit(main())
