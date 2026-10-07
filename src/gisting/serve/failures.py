import threading
from abc import ABC, abstractmethod
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import NamedTuple

from gisting.serve.config import Limits

SESSION_KIND = "session"
IP_KIND = "ip"
IP_UNKNOWN = "unknown"
EVICTED = "failure_store_evicted"
IP_DIGEST_MISSING = "ip_digest_missing"

Key = tuple[str, str]


class Entry(NamedTuple):
    failures: int
    last_failure_at: float


@dataclass(frozen=True)
class FailureLimits:
    session: int
    ip: int
    ttl_s: float
    max_keys: int

    @classmethod
    def from_limits(cls, limits: Limits, session_limit: int) -> "FailureLimits":
        return cls(
            session_limit, limits.ip_failure_limit, limits.failure_ttl_s, limits.max_failure_keys
        )


@dataclass(frozen=True)
class FailureStats:
    evicted: int
    ip_digest_missing: int


@dataclass(frozen=True)
class FailureSnapshot:
    counts: dict[Key, int]
    spent: dict[Key, int] = field(default_factory=lambda: {})


def keys_for(session_id: str, ip_digest: str | None) -> tuple[Key, ...]:
    return (SESSION_KIND, session_id), (IP_KIND, ip_digest or IP_UNKNOWN)


class FailureStore:
    def __init__(
        self,
        limits: FailureLimits,
        clock: Callable[[], float],
        on_degraded: Callable[[str], None] = lambda _reason: None,
    ) -> None:
        self._limits = limits
        self._clock = clock
        self._on_degraded = on_degraded
        self._lock = threading.Lock()
        self._tables: dict[str, OrderedDict[str, Entry]] = {
            SESSION_KIND: OrderedDict(),
            IP_KIND: OrderedDict(),
        }
        self._evicted = 0
        self._ip_digest_missing = 0

    def live(self, ip_digest: str | None) -> "LiveFailures":
        return LiveFailures(self, ip_digest)

    def replay(self, ip_digest: str | None, before: FailureSnapshot) -> "ReplayFailures":
        return ReplayFailures(self, ip_digest, before)

    def stats(self) -> FailureStats:
        with self._lock:
            return FailureStats(self._evicted, self._ip_digest_missing)

    def limit(self, kind: str) -> int:
        return self._limits.session if kind == SESSION_KIND else self._limits.ip

    def count(self, key: Key) -> int:
        with self._lock:
            now = self._clock()
            self._purge(now)
            return self._count(key, now)

    def record(self, session_id: str, ip_digest: str | None) -> bool:
        with self._lock:
            now = self._clock()
            keys = keys_for(session_id, ip_digest)
            self._purge(now)
            counted = not self._locked(keys, now)
            evictions = sum(self._bump(k, now) for k in keys) if counted else 0
        for _ in range(evictions):
            self._on_degraded(EVICTED)
        return counted

    def note_ip_digest_missing(self) -> None:
        with self._lock:
            self._ip_digest_missing += 1
        self._on_degraded(IP_DIGEST_MISSING)

    def _expired(self, entry: Entry, now: float) -> bool:
        return now - entry.last_failure_at >= self._limits.ttl_s

    def _count(self, key: Key, now: float) -> int:
        entry = self._tables[key[0]].get(key[1])
        return 0 if entry is None or self._expired(entry, now) else entry.failures

    def _locked(self, keys: tuple[Key, ...], now: float) -> bool:
        return any(self._count(key, now) >= self.limit(key[0]) for key in keys)

    def _purge(self, now: float) -> None:
        for table in self._tables.values():
            while table and self._expired(next(iter(table.values())), now):
                table.popitem(last=False)

    def _bump(self, key: Key, now: float) -> int:
        table = self._tables[key[0]]
        previous = self._count(key, now)
        table.pop(key[1], None)
        table[key[1]] = Entry(previous + 1, now)
        evicted = 0
        while len(table) > self._limits.max_keys:
            table.popitem(last=False)
            self._evicted += 1
            evicted += 1
        return evicted


class FailureView(ABC):
    def __init__(self, store: FailureStore, ip_digest: str | None) -> None:
        self._store = store
        self._ip_digest = ip_digest

    def failures(self, session_id: str) -> int:
        self._enter(session_id)
        return self._count((SESSION_KIND, session_id))

    def is_locked(self, session_id: str) -> bool:
        self._enter(session_id)
        return self._locked(session_id)

    def record_failure(self, session_id: str) -> None:
        self._enter(session_id)
        self._record(session_id)

    def _enter(self, session_id: str) -> None:
        return None

    def _locked(self, session_id: str) -> bool:
        keys = keys_for(session_id, self._ip_digest)
        return any(self._count(key) >= self._store.limit(key[0]) for key in keys)

    @abstractmethod
    def _count(self, key: Key) -> int: ...

    @abstractmethod
    def _record(self, session_id: str) -> None: ...


class LiveFailures(FailureView):
    def __init__(self, store: FailureStore, ip_digest: str | None) -> None:
        super().__init__(store, ip_digest)
        self._reported_missing = False
        self._first_seen: dict[Key, int] = {}
        self._spent: dict[Key, int] = {}

    def before(self) -> FailureSnapshot:
        return FailureSnapshot(dict(self._first_seen), dict(self._spent))

    def _enter(self, session_id: str) -> None:
        if not self._ip_digest and not self._reported_missing:
            self._reported_missing = True
            self._store.note_ip_digest_missing()
        for key in keys_for(session_id, self._ip_digest):
            if key not in self._first_seen:
                self._first_seen[key] = self._store.count(key)

    def _count(self, key: Key) -> int:
        return self._store.count(key)

    def _record(self, session_id: str) -> None:
        if self._store.record(session_id, self._ip_digest):
            for key in keys_for(session_id, self._ip_digest):
                self._spent[key] = self._spent.get(key, 0) + 1


class ReplayFailures(FailureView):
    def __init__(self, store: FailureStore, ip_digest: str | None, before: FailureSnapshot) -> None:
        super().__init__(store, ip_digest)
        self._before = before
        self._added: dict[Key, int] = {}

    def _count(self, key: Key) -> int:
        spare = max(self._before.spent.get(key, 0) - self._added.get(key, 0), 0)
        return max(self._store.count(key) - spare, 0)

    def _record(self, session_id: str) -> None:
        if self._locked(session_id):
            return
        keys = keys_for(session_id, self._ip_digest)
        excess = False
        for key in keys:
            self._added[key] = self._added.get(key, 0) + 1
            excess = excess or self._added[key] > self._before.spent.get(key, 0)
        if excess:
            self._store.record(session_id, self._ip_digest)
