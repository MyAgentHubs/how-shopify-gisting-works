import argparse
import subprocess
import sys
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

TOP_LEVEL_EXCLUDED = frozenset({
    "legacy",
    "shopify-app",
    "artifacts",
    "dist",
    "build",
    "bin",
    "lib",
    "include",
})
ANY_LEVEL_EXCLUDED = frozenset({
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    "generated",
    ".pytest_cache",
    ".ruff_cache",
})
GENERATED_SUFFIXES = (".generated.ts", ".generated.tsx", ".d.ts")
TEST_DIR_NAMES = frozenset({"tests", "__tests__"})
TEST_NAME_MARKERS = (".test.", ".spec.")


@dataclass(frozen=True)
class Violation:
    path: str
    line: int
    reason: str


def default_root() -> Path:
    return Path(__file__).resolve().parents[1]


def make_parser(description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--root", type=Path, default=default_root())
    return parser


def parse_root(description: str, argv: Sequence[str] | None) -> Path:
    return make_parser(description).parse_args(argv).root.resolve()


def report(violations: Iterable[Violation]) -> int:
    found = sorted(set(violations), key=lambda item: (item.path, item.line, item.reason))
    for item in found:
        sys.stderr.write(f"{item.path}:{item.line}: {item.reason}\n")
    return 1 if found else 0


def is_excluded(relative: Path) -> bool:
    parts = relative.parts
    if parts[0] in TOP_LEVEL_EXCLUDED:
        return True
    if any(part in ANY_LEVEL_EXCLUDED for part in parts[:-1]):
        return True
    return relative.name.endswith(GENERATED_SUFFIXES)


def is_test_file(relative: Path) -> bool:
    name = relative.name
    if any(part in TEST_DIR_NAMES for part in relative.parts[:-1]):
        return True
    if name.startswith("test_") or name == "conftest.py":
        return True
    return any(marker in name for marker in TEST_NAME_MARKERS)


def candidate_paths(root: Path) -> list[Path]:
    if not (root / ".git").exists():
        return sorted(root.rglob("*"))
    listing = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        capture_output=True,
        check=True,
        text=True,
    )
    return [root / name for name in sorted(listing.stdout.split("\0")) if name]


def iter_files(
    root: Path, suffixes: Iterable[str], *, subdirs: Sequence[str] = ()
) -> Iterator[Path]:
    wanted = tuple(suffixes)
    bases = [root / name for name in subdirs] or [root]
    for path in candidate_paths(root):
        in_scope = any(path.is_relative_to(base) for base in bases)
        matches = in_scope and path.is_file() and path.name.endswith(wanted)
        if matches and not is_excluded(path.relative_to(root)):
            yield path


def rel(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def non_blank_lines(text: str) -> int:
    return sum(1 for line in text.splitlines() if line.strip())
