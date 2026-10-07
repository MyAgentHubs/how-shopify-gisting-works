from dataclasses import dataclass

from gisting.prompt.messages import Message

RAW = "raw"
FINAL = "final"
DECISION = "decision"
FIRST = "first"
SECOND = "second"


@dataclass(frozen=True)
class Case:
    category: str
    kind: str
    scenario: str | None
    order_number: str | None
    email: str | None
    messages: tuple[Message, ...]


@dataclass(frozen=True)
class Verdict:
    ok: bool
    problems: tuple[str, ...]
