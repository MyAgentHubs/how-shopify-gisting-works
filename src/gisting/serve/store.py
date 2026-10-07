import threading
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, replace

from gisting.serve.config import Limits
from gisting.serve.failures import FailureSnapshot


@dataclass(frozen=True)
class StoreLimits:
    ttl_s: float
    max_sessions: int
    max_turns: int
    max_bytes: int

    @classmethod
    def from_limits(cls, limits: Limits) -> "StoreLimits":
        return cls(
            limits.session_ttl_s,
            limits.max_sessions,
            limits.max_turns_per_session,
            limits.max_session_bytes,
        )


@dataclass(frozen=True)
class Exchange:
    user: str
    assistant: str


@dataclass(frozen=True)
class Committed:
    reset: bool


@dataclass(frozen=True)
class CompareHistory:
    exchanges: tuple[Exchange, ...]
    failures: FailureSnapshot


@dataclass(frozen=True)
class CompareUnavailable:
    pass


@dataclass(frozen=True)
class Record:
    exchanges: tuple[Exchange, ...]
    before_last: tuple[Exchange, ...]
    failures_before_last: FailureSnapshot
    last_used: float
    compared: bool = False


def exchange_bytes(exchange: Exchange) -> int:
    user = exchange.user.encode("utf-8", "surrogatepass")
    return len(user) + len(exchange.assistant.encode("utf-8", "surrogatepass"))


class SessionStore:
    def __init__(self, limits: StoreLimits, clock: Callable[[], float]) -> None:
        self._limits = limits
        self._clock = clock
        self._lock = threading.Lock()
        self._records: OrderedDict[str, Record] = OrderedDict()

    def history(self, session_id: str) -> tuple[Exchange, ...]:
        with self._lock:
            record = self._live(session_id)
            return record.exchanges if record else ()

    def size(self) -> int:
        with self._lock:
            return len(self._records)

    def compare_history(self, session_id: str, message: str) -> CompareHistory | CompareUnavailable:
        with self._lock:
            record = self._live(session_id)
            if record is None or not record.exchanges or record.exchanges[-1].user != message:
                return CompareUnavailable()
            if record.compared:
                return CompareUnavailable()
            self._records[session_id] = replace(record, compared=True)
            return CompareHistory(record.before_last, record.failures_before_last)

    def commit(
        self, session_id: str, user: str, assistant: str, failures_before: FailureSnapshot
    ) -> Committed:
        with self._lock:
            now = self._clock()
            self._purge(now)
            earlier = self._records.get(session_id)
            prior = earlier.exchanges if earlier else ()
            kept = (*prior, Exchange(user, assistant))
            over_limit = self._too_big(kept)
            self._records.pop(session_id, None)
            if over_limit:
                return Committed(True)
            self._records[session_id] = Record(kept, prior, failures_before, now)
            while len(self._records) > self._limits.max_sessions:
                self._records.popitem(last=False)
            return Committed(False)

    def _expired(self, record: Record, now: float) -> bool:
        return now - record.last_used >= self._limits.ttl_s

    def _live(self, session_id: str) -> Record | None:
        record = self._records.get(session_id)
        if record is None or self._expired(record, self._clock()):
            return None
        return record

    def _purge(self, now: float) -> None:
        while self._records:
            oldest = next(iter(self._records.values()))
            if not self._expired(oldest, now):
                return
            self._records.popitem(last=False)

    def _too_big(self, exchanges: tuple[Exchange, ...]) -> bool:
        too_many = len(exchanges) > self._limits.max_turns
        return too_many or sum(map(exchange_bytes, exchanges)) > self._limits.max_bytes
