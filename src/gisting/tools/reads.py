from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class LookupRead:
    shopify_ms: float | None
    result_type: str
    cache_hit: bool | None


class OpenRead(Protocol):
    def finish(self, read: LookupRead) -> None: ...

    def interrupt(self, error_type: str) -> None: ...


class LookupSink(Protocol):
    def begin(self) -> OpenRead: ...


@dataclass(frozen=True)
class Discard:
    def begin(self) -> "Discard":
        return self

    def finish(self, read: LookupRead) -> None:
        return None

    def interrupt(self, error_type: str) -> None:
        return None


DISCARD = Discard()
