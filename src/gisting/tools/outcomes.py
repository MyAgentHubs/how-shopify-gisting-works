from dataclasses import dataclass
from enum import StrEnum

from gisting.tools.facts import OrderFacts


class MismatchStage(StrEnum):
    INPUT_EMAIL = "input_email"
    READBACK_EMAIL = "readback_email"


@dataclass(frozen=True)
class Found:
    facts: OrderFacts


@dataclass(frozen=True)
class Malformed:
    pass


@dataclass(frozen=True)
class OutOfRange:
    pass


@dataclass(frozen=True)
class Mismatch:
    stage: MismatchStage


@dataclass(frozen=True)
class NotFound:
    pass


@dataclass(frozen=True)
class NotDemoOrder:
    pass


@dataclass(frozen=True)
class UpstreamError:
    reason: str


@dataclass(frozen=True)
class Locked:
    pass


NoMatch = Malformed | OutOfRange | Mismatch | NotFound | NotDemoOrder
NO_MATCH_TYPES = (Malformed, OutOfRange, Mismatch, NotFound, NotDemoOrder)
LookupOutcome = Found | NoMatch | UpstreamError | Locked


@dataclass(frozen=True)
class PolicyHit:
    id: str
    category: str
    title: str
    answer: str


@dataclass(frozen=True)
class PolicyFound:
    hits: tuple[PolicyHit, ...]


@dataclass(frozen=True)
class PolicyNoMatch:
    pass


@dataclass(frozen=True)
class PolicyUnavailable:
    reason: str


PolicyOutcome = PolicyFound | PolicyNoMatch | PolicyUnavailable
