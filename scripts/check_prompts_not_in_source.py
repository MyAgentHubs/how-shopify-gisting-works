#!/usr/bin/env python3
import bisect
import sys
from collections.abc import Iterator, Sequence
from pathlib import Path

import guardlib
from guardlib import Violation

MIN_LINE_CHARS = 20
DATA_DIRS = ("prompts", "kb", "eval/cases")
SOURCE_DIRS = ("src", "apps")
SOURCE_SUFFIXES = (".py", ".ts", ".tsx", ".js", ".jsx", ".mjs")


def normalize(text: str) -> str:
    return " ".join(text.split()).lower()


def data_files(root: Path) -> Iterator[Path]:
    for name in DATA_DIRS:
        base = root / name
        if base.is_dir():
            yield from (path for path in sorted(base.rglob("*")) if path.is_file())


def data_lines(root: Path) -> Iterator[tuple[str, int, str]]:
    for path in data_files(root):
        text = path.read_text(encoding="utf-8", errors="ignore")
        for number, line in enumerate(text.splitlines(), start=1):
            needle = normalize(line)
            if len(needle) >= MIN_LINE_CHARS:
                yield guardlib.rel(root, path), number, needle


def index_source(text: str) -> tuple[str, list[int]]:
    chunks: list[str] = []
    starts: list[int] = []
    offset = 0
    for line in text.splitlines():
        chunk = normalize(line)
        if chunk:
            chunks.append(chunk)
            starts.append(offset)
            offset += len(chunk) + 1
    return " ".join(chunks), starts


def source_files(root: Path) -> Iterator[Path]:
    for path in guardlib.iter_files(root, SOURCE_SUFFIXES, subdirs=SOURCE_DIRS):
        if not guardlib.is_test_file(path.relative_to(root)):
            yield path


def source_line_numbers(text: str) -> list[int]:
    return [number for number, line in enumerate(text.splitlines(), start=1) if normalize(line)]


def find_violations(root: Path) -> list[Violation]:
    needles = list(data_lines(root))
    found: list[Violation] = []
    if not needles:
        return found
    for path in source_files(root):
        text = path.read_text(encoding="utf-8", errors="ignore")
        haystack, starts = index_source(text)
        numbers = source_line_numbers(text)
        for origin, origin_line, needle in needles:
            position = haystack.find(needle)
            if position >= 0:
                line = numbers[bisect.bisect_right(starts, position) - 1]
                reason = f"contains data line from {origin}:{origin_line}"
                found.append(Violation(guardlib.rel(root, path), line, reason))
    return found


def main(argv: Sequence[str] | None = None) -> int:
    root = guardlib.parse_root("Fail when data-directory lines appear in source.", argv)
    return guardlib.report(find_violations(root))


if __name__ == "__main__":
    sys.exit(main())
