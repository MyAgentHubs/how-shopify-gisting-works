import time
from dataclasses import dataclass, field

from serve_support import Call, FakeTurn, make_service

from gisting.serve.contract import GenerateRequest
from gisting.serve.deadline import DeadlineExceeded
from gisting.serve.failures import (
    FailureLimits,
    FailureSnapshot,
    FailureStore,
    LiveFailures,
    ReplayFailures,
)
from gisting.serve.service import Refused, Served, Service
from gisting.serve.store import CompareHistory, Exchange, SessionStore, StoreLimits

SESSION = "session-0001"
SESSION_KEY = ("session", SESSION)
IP = "ip-digest-1"
OTHER_IP = "ip-digest-2"


def gist(message: str, session: str = SESSION) -> GenerateRequest:
    return GenerateRequest(session, message, "gist")


def full(message: str, session: str = SESSION) -> GenerateRequest:
    return GenerateRequest(session, message, "full")


def build(
    turn: FakeTurn, session: int = 5, ip: int = 20, store_limits: StoreLimits | None = None
) -> Service:
    service = make_service(turn, store_limits=store_limits)
    service.failures = FailureStore(FailureLimits(session, ip, 1000.0, 50), time.monotonic)
    return service


def prefill(service: Service, times: int, session: str = SESSION, ip: str = IP) -> None:
    view = service.failures.live(ip)
    for _ in range(times):
        view.record_failure(session)


def stored(service: Service, session: str = SESSION) -> int:
    return service.failures.count(("session", session))


@dataclass
class Observer:
    fail_times: dict[str, int]
    seen: dict[str, list[tuple[int, bool]]] = field(default_factory=lambda: {})

    def __call__(self, call: Call) -> None:
        steps = self.seen.setdefault(call.mode, [])
        who = call.session_id
        steps.append((call.failures.failures(who), call.failures.is_locked(who)))
        for _ in range(self.fail_times.get(call.mode, 0)):
            call.failures.record_failure(who)
            steps.append((call.failures.failures(who), call.failures.is_locked(who)))


def compare(service: Service, message: str, ip: str | None = IP) -> None:
    assert isinstance(service.handle(gist(message), ip).result, Served)
    assert isinstance(service.handle(full(message), ip).result, Served)


def test_the_full_turn_sees_the_count_from_before_the_gist_turn_and_nothing_is_counted_twice() -> (
    None
):
    observer = Observer({"gist": 1, "full": 1})
    service = build(FakeTurn(act=observer))
    prefill(service, 4)
    compare(service, "where is it")
    assert observer.seen["gist"] == [(4, False), (5, True)]
    assert observer.seen["full"] == [(4, False), (5, True)]
    assert stored(service) == 5


def test_a_full_turn_that_would_not_lock_leaves_the_shared_count_untouched() -> None:
    observer = Observer({"gist": 1, "full": 1})
    service = build(FakeTurn(act=observer))
    prefill(service, 1)
    compare(service, "where is it")
    assert observer.seen["gist"] == [(1, False), (2, False)]
    assert observer.seen["full"] == [(1, False), (2, False)]
    assert stored(service) == 2


def test_two_failures_in_the_gist_turn_lock_on_the_second_and_the_full_turn_agrees() -> None:
    observer = Observer({"gist": 2, "full": 2})
    service = build(FakeTurn(act=observer), session=2)
    compare(service, "where is it")
    assert observer.seen["gist"] == [(0, False), (1, False), (2, True)]
    assert observer.seen["full"] == observer.seen["gist"]
    assert stored(service) == 2


def test_a_session_locked_before_the_gist_turn_is_locked_in_the_full_turn_too() -> None:
    observer = Observer({"gist": 1, "full": 1})
    service = build(FakeTurn(act=observer))
    prefill(service, 5)
    compare(service, "where is it")
    assert observer.seen["gist"] == [(5, True), (5, True)]
    assert observer.seen["full"] == [(5, True), (5, True)]
    assert stored(service) == 5


def test_gist_uses_the_live_view_and_full_uses_the_replay_view() -> None:
    turn = FakeTurn()
    service = build(turn)
    compare(service, "where is it")
    assert isinstance(turn.calls[0].failures, LiveFailures)
    assert isinstance(turn.calls[1].failures, ReplayFailures)
    assert [call.mode for call in turn.calls] == ["gist", "full"]


def test_an_uncommitted_gist_turns_failures_stay_counted_and_full_replays_the_commit() -> None:
    def timing_out(call: Call) -> None:
        call.failures.record_failure(SESSION)
        raise DeadlineExceeded

    turn = FakeTurn(act=lambda call: call.failures.record_failure(SESSION))
    service = build(turn)
    assert isinstance(service.handle(gist("hi"), IP).result, Served)
    assert stored(service) == 1
    turn.act = timing_out
    assert service.handle(gist("hi"), IP).result == Refused("timeout")
    assert stored(service) == 2
    observer = Observer({"full": 1})
    turn.act = observer
    assert isinstance(service.handle(full("hi"), IP).result, Served)
    assert observer.seen["full"] == [(1, False), (2, False)]
    assert stored(service) == 2


def test_the_snapshot_rides_on_the_exchange_it_was_committed_with() -> None:
    store = SessionStore(StoreLimits(100.0, 3, 5, 10_000), time.monotonic)
    first, second = FailureSnapshot({SESSION_KEY: 1}), FailureSnapshot({SESSION_KEY: 3})
    store.commit(SESSION, "a", "r1", first)
    assert store.compare_history(SESSION, "a") == CompareHistory((), first)
    store.commit(SESSION, "b", "r2", second)
    assert store.compare_history(SESSION, "b") == CompareHistory((Exchange("a", "r1"),), second)
    assert store.compare_history(SESSION, "a") != CompareHistory((), first)


def test_a_new_ip_key_the_snapshot_never_saw_reads_its_live_value() -> None:
    observer = Observer({"gist": 1})
    service = build(FakeTurn(act=observer), session=5, ip=3)
    assert isinstance(service.handle(gist("hi"), IP).result, Served)
    prefill(service, 3, session="elsewhere", ip=OTHER_IP)
    assert isinstance(service.handle(full("hi"), OTHER_IP).result, Served)
    assert observer.seen["gist"] == [(0, False), (1, False)]
    assert observer.seen["full"] == [(0, True)]
    assert stored(service) == 1


def test_a_missing_ip_digest_is_counted_once_for_the_whole_compare_request() -> None:
    observer = Observer({"gist": 1, "full": 1})
    service = build(FakeTurn(act=observer))
    compare(service, "hi", ip=None)
    assert service.failures.stats().ip_digest_missing == 1
    assert observer.seen["full"] == observer.seen["gist"]


def test_a_reset_over_the_turn_limit_makes_compare_unavailable_without_zeroing_failures() -> None:
    observer = Observer({"gist": 1})
    service = build(FakeTurn(act=observer), store_limits=StoreLimits(900.0, 10, 1, 16384))
    assert isinstance(service.handle(gist("first"), IP).result, Served)
    switched = service.handle(gist("second"), IP)
    assert switched.timing.session_reset
    assert service.handle(full("second"), IP).result == Refused("compare_unavailable")
    assert stored(service) == 2


def test_an_evicted_session_makes_compare_unavailable_without_zeroing_failures() -> None:
    observer = Observer({"gist": 2})
    service = build(FakeTurn(act=observer), store_limits=StoreLimits(900.0, 1, 5, 16384))
    assert isinstance(service.handle(gist("mine", "session-aaaa"), IP).result, Served)
    assert isinstance(service.handle(gist("yours", "session-bbbb"), IP).result, Served)
    assert service.handle(full("mine", "session-aaaa"), IP).result == Refused("compare_unavailable")
    assert stored(service, "session-aaaa") == 2
