import random
import threading
from dataclasses import dataclass, field

import pytest

from gisting.serve.config import LIMITS
from gisting.serve.failures import FailureSnapshot
from gisting.serve.store import (
    Committed,
    CompareHistory,
    CompareUnavailable,
    Exchange,
    SessionStore,
    StoreLimits,
)

NONE = FailureSnapshot({})


@dataclass
class Clock:
    now: float = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def make_store(
    clock: Clock, ttl: float = 100.0, sessions: int = 3, turns: int = 4, size: int = 10_000
) -> SessionStore:
    return SessionStore(StoreLimits(ttl, sessions, turns, size), clock)


def test_limits_come_from_the_data_file() -> None:
    limits = StoreLimits.from_limits(LIMITS)
    assert limits.ttl_s == LIMITS.session_ttl_s
    assert limits.max_sessions == LIMITS.max_sessions
    assert limits.max_turns == LIMITS.max_turns_per_session
    assert limits.max_bytes == LIMITS.max_session_bytes


def test_unknown_session_has_no_history() -> None:
    assert make_store(Clock()).history("nobody") == ()


def test_commit_appends_in_order() -> None:
    store = make_store(Clock())
    assert store.commit("s", "hi", "hello", NONE) == Committed(False)
    store.commit("s", "order?", "which one", NONE)
    assert store.history("s") == (Exchange("hi", "hello"), Exchange("order?", "which one"))


def test_idle_session_expires_at_the_ttl() -> None:
    clock = Clock()
    store = make_store(clock)
    store.commit("s", "a", "b", NONE)
    clock.advance(99.9)
    assert store.history("s") == (Exchange("a", "b"),)
    clock.advance(0.1)
    assert store.history("s") == ()


def test_commit_refreshes_the_ttl_but_reads_do_not() -> None:
    clock = Clock()
    store = make_store(clock)
    store.commit("s", "a", "b", NONE)
    clock.advance(60)
    store.history("s")
    store.compare_history("s", "a")
    clock.advance(60)
    assert store.history("s") == ()
    store.commit("s", "a", "b", NONE)
    clock.advance(60)
    store.commit("s", "c", "d", NONE)
    clock.advance(60)
    assert len(store.history("s")) == 2


def test_an_expired_session_restarts_empty() -> None:
    clock = Clock()
    store = make_store(clock)
    store.commit("s", "old", "reply", NONE)
    clock.advance(100)
    store.commit("s", "new", "reply", NONE)
    assert store.history("s") == (Exchange("new", "reply"),)


def test_least_recently_committed_session_is_evicted() -> None:
    clock = Clock()
    store = make_store(clock)
    for name in ("a", "b", "c"):
        clock.advance(1)
        store.commit(name, name, name, NONE)
    clock.advance(1)
    store.commit("a", "again", "again", NONE)
    store.history("b")
    store.compare_history("b", "b")
    clock.advance(1)
    store.commit("d", "d", "d", NONE)
    assert store.history("b") == ()
    assert {name for name in "acd" if store.history(name)} == set("acd")
    assert store.size() == 3


def test_going_over_the_turn_cap_clears_the_whole_session() -> None:
    store = make_store(Clock(), turns=3)
    results = [store.commit("s", f"u{i}", f"a{i}", NONE) for i in range(3)]
    assert results == [Committed(False)] * 3
    assert store.commit("s", "u3", "a3", NONE) == Committed(True)
    assert store.history("s") == ()
    assert store.compare_history("s", "u3") == CompareUnavailable()
    assert store.commit("s", "u4", "a4", NONE) == Committed(False)
    assert store.history("s") == (Exchange("u4", "a4"),)


def test_going_over_the_byte_cap_clears_the_whole_session() -> None:
    store = make_store(Clock(), turns=50, size=20)
    store.commit("s", "aaaa", "bbbb", NONE)
    store.commit("s", "cccc", "dddd", NONE)
    assert store.commit("s", "eeee", "ffff", NONE) == Committed(True)
    assert store.history("s") == ()


def test_the_byte_cap_is_counted_in_utf8() -> None:
    store = make_store(Clock(), turns=50, size=12)
    store.commit("s", "éé", "éé", NONE)
    assert store.commit("s", "éé", "éé", NONE) == Committed(True)


def test_a_single_turn_that_alone_is_too_big_is_not_kept() -> None:
    store = make_store(Clock(), size=5)
    assert store.commit("s", "u" * 50, "a" * 50, NONE) == Committed(True)
    assert store.history("s") == ()


def test_a_reset_does_not_touch_other_sessions() -> None:
    store = make_store(Clock(), turns=1)
    store.commit("other", "keep", "me", NONE)
    store.commit("s", "a", "b", NONE)
    store.commit("s", "c", "d", NONE)
    assert store.history("other") == (Exchange("keep", "me"),)


def test_a_lone_surrogate_is_counted_and_never_breaks_the_history() -> None:
    store = make_store(Clock())
    store.commit("s", "first", "r1", NONE)
    assert store.commit("s", "second", "\ud83d", NONE) == Committed(False)
    assert store.history("s") == (Exchange("first", "r1"), Exchange("second", "\ud83d"))


class Bomb(str):
    def encode(self, encoding: str = "utf-8", errors: str = "strict") -> bytes:
        raise RuntimeError


def test_a_failing_commit_leaves_the_history_as_it_was() -> None:
    store = make_store(Clock())
    store.commit("s", "first", "r1", NONE)
    store.commit("s", "second", "r2", NONE)
    with pytest.raises(RuntimeError):
        store.commit("s", "third", Bomb("r3"), NONE)
    assert store.history("s") == (Exchange("first", "r1"), Exchange("second", "r2"))
    assert store.compare_history("s", "second") == CompareHistory((Exchange("first", "r1"),), NONE)


def test_compare_needs_a_committed_turn() -> None:
    store = make_store(Clock())
    assert store.compare_history("s", "hi") == CompareUnavailable()


def test_compare_needs_the_last_user_message_verbatim() -> None:
    store = make_store(Clock())
    store.commit("s", "first", "r1", NONE)
    store.commit("s", "second", "r2", NONE)
    assert store.compare_history("s", "first") == CompareUnavailable()
    assert store.compare_history("s", "second ") == CompareUnavailable()
    assert store.compare_history("other", "second") == CompareUnavailable()


def test_compare_returns_the_history_before_the_last_turn() -> None:
    store = make_store(Clock())
    store.commit("s", "first", "r1", NONE)
    assert store.compare_history("s", "first") == CompareHistory((), NONE)
    store.commit("s", "second", "r2", NONE)
    assert store.compare_history("s", "second") == CompareHistory((Exchange("first", "r1"),), NONE)


def test_compare_after_expiry_is_unavailable() -> None:
    clock = Clock()
    store = make_store(clock)
    store.commit("s", "first", "r1", NONE)
    clock.advance(100)
    assert store.compare_history("s", "first") == CompareUnavailable()


def test_concurrent_commits_to_one_session_lose_nothing() -> None:
    store = make_store(Clock(), turns=1000, size=10**9)

    def worker(index: int) -> None:
        for turn in range(25):
            store.commit("shared", f"{index}-{turn}", "ok", NONE)

    threads = [threading.Thread(target=worker, args=(index,)) for index in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    users = [exchange.user for exchange in store.history("shared")]
    assert len(users) == 200
    for index in range(8):
        own = [user for user in users if user.startswith(f"{index}-")]
        assert own == [f"{index}-{turn}" for turn in range(25)]


def test_concurrent_commits_across_sessions_respect_the_capacity() -> None:
    store = make_store(Clock(), sessions=5, turns=2)

    def worker(index: int) -> None:
        for turn in range(40):
            store.commit(f"s{index}-{turn % 7}", "u", "a", NONE)
            store.history(f"s{index}-{turn % 7}")

    threads = [threading.Thread(target=worker, args=(index,)) for index in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert store.size() <= 5


@dataclass
class Reference:
    limits: StoreLimits
    order: list[str] = field(default_factory=lambda: [])
    turns: dict[str, list[tuple[str, str]]] = field(default_factory=lambda: {})
    used: dict[str, float] = field(default_factory=lambda: {})

    def live(self, name: str, now: float) -> bool:
        return name in self.turns and now - self.used[name] < self.limits.ttl_s

    def history(self, name: str, now: float) -> tuple[Exchange, ...]:
        if not self.live(name, now):
            return ()
        return tuple(Exchange(user, reply) for user, reply in self.turns[name])

    def commit(self, name: str, user: str, reply: str, now: float) -> None:
        for other in [key for key in self.order if not self.live(key, now)]:
            self.drop(other)
        earlier = self.turns.get(name, [])
        if name in self.turns:
            self.order.remove(name)
        turns = [*earlier, (user, reply)]
        size = sum(len(u.encode()) + len(a.encode()) for u, a in turns)
        if name in self.turns:
            del self.turns[name]
            del self.used[name]
        if len(turns) > self.limits.max_turns or size > self.limits.max_bytes:
            return
        self.turns[name] = turns
        self.used[name] = now
        self.order.append(name)
        while len(self.order) > self.limits.max_sessions:
            self.drop(self.order[0])

    def drop(self, name: str) -> None:
        self.order.remove(name)
        del self.turns[name]
        del self.used[name]


@pytest.mark.parametrize("seed", range(12))
def test_random_operations_match_a_reference_model(seed: int) -> None:
    generator = random.Random(seed)
    clock = Clock()
    limits = StoreLimits(
        generator.choice([5.0, 30.0, 1000.0]),
        generator.randint(1, 5),
        generator.randint(1, 4),
        generator.randint(8, 60),
    )
    store = SessionStore(limits, clock)
    reference = Reference(limits)
    names = [f"s{index}" for index in range(8)]
    for _ in range(300):
        name = generator.choice(names)
        action = generator.choice(["commit", "commit", "read", "compare", "wait"])
        if action == "commit":
            user = "u" * generator.randint(1, 6)
            reply = "é" * generator.randint(1, 5)
            store.commit(name, user, reply, NONE)
            reference.commit(name, user, reply, clock.now)
        elif action == "wait":
            clock.advance(generator.choice([0.5, 3.0, 20.0]))
        elif action == "compare":
            before = {key: store.history(key) for key in names}
            store.compare_history(name, "u")
            assert {key: store.history(key) for key in names} == before
        for key in names:
            assert store.history(key) == reference.history(key, clock.now)
        assert store.size() <= limits.max_sessions
        assert all(len(store.history(key)) <= limits.max_turns for key in names)


class Pausing(str):
    entered: threading.Event
    release: threading.Event

    def __new__(cls, text: str, entered: threading.Event, release: threading.Event) -> "Pausing":
        instance = super().__new__(cls, text)
        instance.entered = entered
        instance.release = release
        return instance

    def encode(self, encoding: str = "utf-8", errors: str = "strict") -> bytes:
        self.entered.set()
        assert self.release.wait(5)
        return super().encode(encoding, errors)


def test_a_commit_in_flight_blocks_other_commits_to_the_same_session() -> None:
    store = make_store(Clock(), turns=10)
    entered, release = threading.Event(), threading.Event()
    first = threading.Thread(
        target=store.commit, args=("s", "first", Pausing("r1", entered, release), NONE), daemon=True
    )
    second = threading.Thread(target=store.commit, args=("s", "second", "r2", NONE), daemon=True)
    first.start()
    assert entered.wait(5)
    second.start()
    second.join(0.3)
    release.set()
    first.join(5)
    second.join(5)
    assert [exchange.user for exchange in store.history("s")] == ["first", "second"]
