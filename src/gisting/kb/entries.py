import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from gisting.kb.jsonvalue import (
    KB_DIR,
    Json,
    KbDataError,
    parse_json,
    read_text,
    required_int,
    required_str,
)

ENTRIES_FILE = KB_DIR / "policy-v1.jsonl"
CATEGORY_SLUG = re.compile(r"[a-z]+(-[a-z]+)*")
ENTRY_ID = re.compile(r"kb-[a-z0-9]+(-[a-z0-9]+)*")
MAX_ID_LENGTH = 64


@dataclass(frozen=True)
class Entry:
    id: str
    category: str
    version: int
    valid_from: str
    source: str
    title: str
    answer: str


def parse_entry(document: Json) -> Entry:
    if not isinstance(document, dict):
        message = "entry must be a JSON object"
        raise KbDataError(message)
    entry = Entry(
        id=required_str(document, "id"),
        category=required_str(document, "category"),
        version=required_int(document, "version"),
        valid_from=required_str(document, "valid_from"),
        source=required_str(document, "source"),
        title=required_str(document, "title"),
        answer=required_str(document, "answer"),
    )
    id_fits = ENTRY_ID.fullmatch(entry.id) and len(entry.id) <= MAX_ID_LENGTH
    if not id_fits or not CATEGORY_SLUG.fullmatch(entry.category):
        message = f"{entry.id}: id or category is not a slug"
        raise KbDataError(message)
    if entry.version < 1:
        message = f"{entry.id}: version must be at least 1"
        raise KbDataError(message)
    try:
        date.fromisoformat(entry.valid_from)
    except ValueError as error:
        message = f"{entry.id}: valid_from is not an ISO date"
        raise KbDataError(message) from error
    return entry


def parse_entries(text: str, source: str) -> tuple[Entry, ...]:
    entries: list[Entry] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if line.strip():
            entries.append(parse_entry(parse_json(line, f"{source}:{number}")))
    ids = [entry.id for entry in entries]
    if not entries or len(set(ids)) != len(ids):
        message = f"{source}: needs at least one entry and unique ids"
        raise KbDataError(message)
    return tuple(entries)


def load_entries(path: Path = ENTRIES_FILE) -> tuple[Entry, ...]:
    return parse_entries(read_text(path), path.name)
