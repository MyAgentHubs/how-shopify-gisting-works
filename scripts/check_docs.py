#!/usr/bin/env python3
import re
import sys
from collections.abc import Sequence
from pathlib import Path

import guardlib
from guardlib import Violation

DOCS_DIR = "docs"
INDEX_NAME = "INDEX.md"
ROOT_FILES = {"README.md": None, "handoff.md": "handoff"}
KIND_BY_DIR = {
    "decisions": "decision",
    "design": "design",
    "guides": "guide",
    "learning/runs": "run",
    "learning/concepts": "concept",
}
LINE_LIMITS = {
    "decision": 60,
    "design": 400,
    "guide": 200,
    "run": 150,
    "concept": 150,
    "handoff": 300,
}
STATUSES = ("current", "superseded")
REQUIRED_FIELDS = ("type", "status", "updated", "summary")
DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}")
LINK_PATTERN = re.compile(r"\]\(([^)\s]+)\)")
IGNORED_NAMES = frozenset({".DS_Store"})


def parse_front_matter(text: str) -> dict[str, str] | None:
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        return None
    fields: dict[str, str] = {}
    for line in lines[1:]:
        if line == "---":
            return fields
        key, separator, value = line.partition(":")
        if separator:
            fields[key.strip()] = value.strip()
    return None


def field_violations(relative: str, kind: str, fields: dict[str, str]) -> list[Violation]:
    found = [
        Violation(relative, 1, f"front matter is missing {name}")
        for name in REQUIRED_FIELDS
        if not fields.get(name)
    ]
    if fields.get("type") and fields["type"] != kind:
        found.append(Violation(relative, 1, f"type {fields['type']} must be {kind} here"))
    if fields.get("status") and fields["status"] not in STATUSES:
        found.append(Violation(relative, 1, f"status {fields['status']} is not current|superseded"))
    if fields.get("updated") and not DATE_PATTERN.fullmatch(fields["updated"]):
        found.append(Violation(relative, 1, "updated must be YYYY-MM-DD"))
    return found


def supersede_violations(root: Path, relative: str, fields: dict[str, str]) -> list[Violation]:
    if fields.get("status") != "superseded":
        return []
    target = fields.get("superseded_by", "")
    if not target:
        return [Violation(relative, 1, "superseded document needs superseded_by")]
    if not (root / target).is_file():
        return [Violation(relative, 1, f"superseded_by {target} does not exist")]
    return []


def document_violations(root: Path, path: Path, kind: str) -> list[Violation]:
    relative = guardlib.rel(root, path)
    text = path.read_text(encoding="utf-8")
    found: list[Violation] = []
    size = len(text.splitlines())
    if size > LINE_LIMITS[kind]:
        found.append(Violation(relative, 1, f"{kind} has {size} lines (max {LINE_LIMITS[kind]})"))
    fields = parse_front_matter(text)
    if fields is None:
        return [*found, Violation(relative, 1, "front matter is missing")]
    return [
        *found,
        *field_violations(relative, kind, fields),
        *supersede_violations(root, relative, fields),
    ]


def classify(root: Path, docs: Path, path: Path) -> list[Violation]:
    relative = path.relative_to(docs).as_posix()
    shown = guardlib.rel(root, path)
    parent = path.parent.relative_to(docs).as_posix()
    found: list[Violation] = []
    if path.suffix == ".html":
        found.append(Violation(shown, 1, "docs must not contain generated HTML"))
    if parent == ".":
        if relative not in ROOT_FILES:
            return [*found, Violation(shown, 1, "docs root allows only README.md and handoff.md")]
        kind = ROOT_FILES[relative]
        return [*found, *document_violations(root, path, kind)] if kind else found
    if path.suffix != ".md" or path.name == INDEX_NAME:
        return found
    kind = KIND_BY_DIR.get(parent)
    if kind is None:
        return [*found, Violation(shown, 1, f"{parent} is not a governed docs directory")]
    return [*found, *document_violations(root, path, kind)]


def index_violations(root: Path, directory: Path, names: list[str]) -> list[Violation]:
    index = directory / INDEX_NAME
    shown = guardlib.rel(root, index)
    if not index.is_file():
        return [Violation(guardlib.rel(root, directory), 1, f"{INDEX_NAME} is missing")]
    targets = {
        link.split("#")[0] for link in LINK_PATTERN.findall(index.read_text(encoding="utf-8"))
    }
    found = [Violation(shown, 1, f"{name} is not listed") for name in names if name not in targets]
    local = (target for target in targets if target and "://" not in target)
    found.extend(
        Violation(shown, 1, f"{target} does not exist")
        for target in sorted(local)
        if not (directory / target).is_file()
    )
    return found


def docs_files(docs: Path) -> list[Path]:
    return [p for p in sorted(docs.rglob("*")) if p.is_file() and p.name not in IGNORED_NAMES]


def find_violations(root: Path) -> list[Violation]:
    docs = root / DOCS_DIR
    if not docs.is_dir():
        return []
    files = docs_files(docs)
    found: list[Violation] = []
    listed: dict[Path, list[str]] = {}
    for path in files:
        found.extend(classify(root, docs, path))
        if path.parent != docs and path.suffix == ".md" and path.name != INDEX_NAME:
            listed.setdefault(path.parent, []).append(path.name)
    for directory, names in sorted(listed.items()):
        found.extend(index_violations(root, directory, names))
    return found


def main(argv: Sequence[str] | None = None) -> int:
    root = guardlib.parse_root("Enforce the docs governance rules in docs/README.md.", argv)
    return guardlib.report(find_violations(root))


if __name__ == "__main__":
    sys.exit(main())
