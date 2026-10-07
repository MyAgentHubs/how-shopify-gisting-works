import json
from collections.abc import Collection, Sequence
from dataclasses import dataclass, field

from gisting.agent.public_trace import MAX_KNOWLEDGE
from gisting.kb.entries import ENTRY_ID, MAX_ID_LENGTH
from gisting.shopify.jsonvalue import Json
from gisting.tools.search_policy import (
    STATUS_FOUND,
    STATUS_NO_MATCH,
    STATUS_UNAVAILABLE,
    TOOL_NAME,
)

METHOD = "bm25"
QUIET_STATUSES = frozenset({STATUS_NO_MATCH, STATUS_UNAVAILABLE})


@dataclass(frozen=True)
class Knowledge:
    public: tuple[dict[str, str], ...]
    dropped: tuple[str, ...]
    truncated: tuple[str, ...]
    malformed: int


@dataclass
class Tally:
    shown: list[str] = field(default_factory=lambda: [])
    dropped: list[str] = field(default_factory=lambda: [])
    truncated: list[str] = field(default_factory=lambda: [])
    malformed: int = 0

    def add_entry(self, entry: Json, known: Collection[str]) -> None:
        identifier = entry.get("id") if isinstance(entry, dict) else None
        if not isinstance(identifier, str):
            self.malformed += 1
        elif not public_id(identifier, known):
            self.dropped.append(identifier)
        elif identifier not in (*self.shown, *self.truncated):
            (self.shown if len(self.shown) < MAX_KNOWLEDGE else self.truncated).append(identifier)

    def add_result(self, text: str, known: Collection[str]) -> None:
        hits = result_hits(text)
        if hits is None:
            self.malformed += 1
        for entry in hits or []:
            self.add_entry(entry, known)


def public_id(identifier: str, known: Collection[str]) -> bool:
    return (
        identifier in known
        and len(identifier) <= MAX_ID_LENGTH
        and ENTRY_ID.fullmatch(identifier) is not None
    )


def result_hits(text: str) -> list[Json] | None:
    try:
        result: Json = json.loads(text)
    except ValueError:
        return None
    if not isinstance(result, dict):
        return None
    status, hits = result.get("status"), result.get("hits")
    if status in QUIET_STATUSES:
        return []
    return hits if status == STATUS_FOUND and isinstance(hits, list) and hits else None


def project_knowledge(
    results: Sequence[tuple[str | None, str | None]], known_ids: Collection[str]
) -> Knowledge:
    tally = Tally()
    for name, text in results:
        if name == TOOL_NAME and text is not None:
            tally.add_result(text, known_ids)
    return Knowledge(
        tuple({"id": item, "method": METHOD} for item in tally.shown),
        tuple(tally.dropped),
        tuple(tally.truncated),
        tally.malformed,
    )
