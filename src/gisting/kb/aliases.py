from collections.abc import Mapping
from pathlib import Path

from gisting.kb.entries import Entry
from gisting.kb.jsonvalue import (
    KB_DIR,
    Json,
    KbDataError,
    optional_strings,
    parse_json,
    read_text,
    required_str,
)

ALIASES_FILE = KB_DIR / "policy-aliases-v1.jsonl"
Aliases = Mapping[str, tuple[str, ...]]


def parse_alias_row(document: Json, known: frozenset[str]) -> tuple[str, tuple[str, ...]]:
    if not isinstance(document, dict) or set(document) != {"id", "aliases"}:
        message = 'alias row must be an object with exactly "id" and "aliases"'
        raise KbDataError(message)
    entry_id = required_str(document, "id")
    aliases = optional_strings(document, "aliases")
    if entry_id not in known:
        message = f"{entry_id}: alias row names an entry that does not exist"
        raise KbDataError(message)
    if not aliases or any(not alias.strip() for alias in aliases):
        message = f"{entry_id}: aliases must be a non-empty list of non-blank strings"
        raise KbDataError(message)
    return entry_id, aliases


def parse_aliases(text: str, source: str, entries: tuple[Entry, ...]) -> Aliases:
    known = frozenset(entry.id for entry in entries)
    rows = [
        parse_alias_row(parse_json(line, f"{source}:{number}"), known)
        for number, line in enumerate(text.splitlines(), start=1)
        if line.strip()
    ]
    if len({entry_id for entry_id, _ in rows}) != len(rows):
        message = f"{source}: duplicate alias row for one entry"
        raise KbDataError(message)
    return dict(rows)


def load_aliases(entries: tuple[Entry, ...], path: Path = ALIASES_FILE) -> Aliases:
    return parse_aliases(read_text(path), path.name, entries)
