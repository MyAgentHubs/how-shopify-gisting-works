import threading
import time

from metering_support import IP, World, serve_once, service_for, wrong
from serve_support import FakeTurn, make_service

from gisting.serve.contract import GenerateRequest
from gisting.serve.deadline import DeadlineExceeded
from gisting.serve.failures import FailureSnapshot
from gisting.serve.service import Refused, Served
from gisting.serve.store import CompareHistory, CompareUnavailable, SessionStore, StoreLimits

SESSION = "session-0001"
NONE = FailureSnapshot({})
UNAVAILABLE = Refused("compare_unavailable")


def gist(message: str) -> GenerateRequest:
    return GenerateRequest(SESSION, message, "gist")


def full(message: str) -> GenerateRequest:
    return GenerateRequest(SESSION, message, "full")


def test_a_second_compare_of_one_gist_commit_is_refused_without_running_a_turn() -> None:
    turn = FakeTurn()
    service = make_service(turn)
    assert isinstance(service.handle(gist("hi"), IP).result, Served)
    assert isinstance(service.handle(full("hi"), IP).result, Served)
    calls = len(turn.calls)
    assert service.handle(full("hi"), IP).result == UNAVAILABLE
    assert len(turn.calls) == calls


def test_a_refused_second_compare_makes_no_lookup_and_leaves_the_failure_count() -> None:
    world = World()
    service = service_for(world)
    world.plan[("full", "m")] = [wrong("g1"), wrong("g2")]
    serve_once(service, SESSION, "m", "gist")
    serve_once(service, SESSION, "m", "full")
    lookups, count = len(world.log), service.failures.count(("session", SESSION))
    assert (lookups, count) == (2, 2)
    assert service.handle(full("m"), IP).result == UNAVAILABLE
    assert len(world.log) == lookups
    assert service.failures.count(("session", SESSION)) == count
    assert service.failures.count(("ip", IP)) == count


def test_a_new_gist_commit_can_be_compared_once_more() -> None:
    turn = FakeTurn()
    service = make_service(turn)
    for message in ("first", "second"):
        assert isinstance(service.handle(gist(message), IP).result, Served)
        assert isinstance(service.handle(full(message), IP).result, Served)
        assert service.handle(full(message), IP).result == UNAVAILABLE


def test_recommitting_the_same_message_makes_a_new_exchange_that_compares_again() -> None:
    service = make_service(FakeTurn())
    assert isinstance(service.handle(gist("hi"), IP).result, Served)
    assert isinstance(service.handle(full("hi"), IP).result, Served)
    assert isinstance(service.handle(gist("hi"), IP).result, Served)
    assert isinstance(service.handle(full("hi"), IP).result, Served)


def test_a_full_turn_that_times_out_still_spends_the_exchange_fail_closed() -> None:
    def timing_out(_call: object) -> None:
        raise DeadlineExceeded

    turn = FakeTurn()
    service = make_service(turn)
    assert isinstance(service.handle(gist("hi"), IP).result, Served)
    turn.act = timing_out
    assert service.handle(full("hi"), IP).result == Refused("timeout")
    turn.act = None
    calls = len(turn.calls)
    assert service.handle(full("hi"), IP).result == UNAVAILABLE
    assert len(turn.calls) == calls


def test_a_full_turn_that_crashes_still_spends_the_exchange_fail_closed() -> None:
    turn = FakeTurn()
    service = make_service(turn)
    assert isinstance(service.handle(gist("hi"), IP).result, Served)
    turn.failure = RuntimeError("boom")
    assert service.handle(full("hi"), IP).result.__class__ is Refused
    turn.failure = None
    assert service.handle(full("hi"), IP).result == UNAVAILABLE


def test_concurrent_compares_of_one_exchange_admit_exactly_one() -> None:
    store = SessionStore(StoreLimits(100.0, 3, 5, 10_000), time.monotonic)
    store.commit(SESSION, "hi", "r1", NONE)
    workers = 16
    barrier = threading.Barrier(workers)
    results: list[object] = []

    def compare() -> None:
        barrier.wait()
        results.append(store.compare_history(SESSION, "hi"))

    threads = [threading.Thread(target=compare) for _ in range(workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert results.count(CompareHistory((), NONE)) == 1
    assert results.count(CompareUnavailable()) == workers - 1


def test_two_compare_requests_in_flight_serve_only_one() -> None:
    hold = threading.Event()
    turn = FakeTurn()
    service = make_service(turn)
    assert isinstance(service.handle(gist("hi"), IP).result, Served)
    turn.hold = hold
    results: list[object] = []

    def compare() -> None:
        results.append(service.handle(full("hi"), IP).result)

    first = threading.Thread(target=compare)
    turn.started.clear()
    first.start()
    assert turn.started.wait(5.0)
    second = threading.Thread(target=compare)
    second.start()
    hold.set()
    first.join(5.0)
    second.join(5.0)
    assert sum(isinstance(result, Served) for result in results) == 1
    assert results.count(UNAVAILABLE) == 1


def test_fifty_repeated_compares_of_one_gist_commit_add_only_the_first_full_excess() -> None:
    world = World()
    service = service_for(world, session=5, ip=20)
    world.plan[("gist", "m")] = []
    world.plan[("full", "m")] = [wrong("g1"), wrong("g2")]
    serve_once(service, SESSION, "m", "gist")
    outcomes = [service.handle(full("m"), IP).result for _ in range(50)]
    assert isinstance(outcomes[0], Served)
    assert outcomes[1:] == [UNAVAILABLE] * 49
    assert world.statuses("full") == ["no_match", "no_match"]
    assert service.failures.count(("session", SESSION)) == 2
    assert service.failures.count(("ip", IP)) == 2
