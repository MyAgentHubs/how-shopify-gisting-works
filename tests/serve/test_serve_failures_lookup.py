import json
import threading

import pytest
from failure_support import IP, SESSION, Rig
from fakes.shopify import FakeOrder, FakeTransport

from gisting.shopify.client import AdminClient
from gisting.shopify.demo_email import demo_email
from gisting.shopify.jsonvalue import JsonObject
from gisting.shopify.order_state import OrderState
from gisting.shopify.results import Cause, NotExecuted
from gisting.shopify.target import BATCH_TAG
from gisting.tools.cache import InMemoryOrderCache
from gisting.tools.factory import build_lookup
from gisting.tools.lookup_order import LookupOrder, ToolResponse
from gisting.tools.policy import load_policy

POLICY = load_policy()
SECRET = "serve-failure-secret"
NUMBER = 1042


class SpyCache(InMemoryOrderCache):
    def __init__(self) -> None:
        super().__init__(60)
        self.gets: list[str] = []
        self.puts: list[str] = []

    def get(self, order_name: str) -> OrderState | None:
        self.gets.append(order_name)
        return super().get(order_name)

    def put(self, order_name: str, order: OrderState) -> None:
        self.puts.append(order_name)
        super().put(order_name, order)


def email_for(number: int) -> str:
    return demo_email(SECRET, f"#{number}")


def demo_order(number: int) -> FakeOrder:
    order = FakeOrder(number, email=email_for(number))
    order.tags = [BATCH_TAG, *POLICY.required_tags]
    return order


class Env:
    def __init__(self, rig: Rig, ip: str | None = IP) -> None:
        self.cache = SpyCache()
        self.fake = FakeTransport([demo_order(NUMBER)])
        view = rig.store.live(ip)
        self.view = view
        client = AdminClient(self.fake, sleep=lambda _seconds: None)
        self.tool: LookupOrder = build_lookup(client, self.cache, view, POLICY, SECRET)

    def lookup(self, number: int, email: str, session: str = SESSION) -> ToolResponse:
        arguments: JsonObject = {"order_number": str(number), "email": email}
        return self.tool.call(arguments, session)

    def io(self) -> tuple[int, int, int]:
        return len(self.cache.gets), len(self.cache.puts), len(self.fake.calls)


def wire(response: ToolResponse) -> str:
    return json.dumps(response.result, sort_keys=True)


def test_mismatch_and_not_found_are_byte_identical_through_the_store() -> None:
    mismatch = Env(Rig().build()).lookup(NUMBER, "wrong@example.com")
    missing = Env(Rig().build()).lookup(NUMBER + 1, email_for(NUMBER + 1))
    assert mismatch.trace.internal.result_type == "Mismatch"
    assert missing.trace.internal.result_type == "NotFound"
    assert wire(mismatch) == wire(missing)


def test_both_kinds_of_no_match_count_against_the_session_and_the_ip() -> None:
    rig = Rig().build(session=2, ip=9)
    env = Env(rig)
    env.lookup(NUMBER, "wrong@example.com")
    env.lookup(NUMBER + 1, email_for(NUMBER + 1))
    assert env.view.failures(SESSION) == 2
    assert env.view.is_locked(SESSION)


def test_verification_runs_before_any_cache_or_upstream_read() -> None:
    env = Env(Rig().build())
    env.lookup(NUMBER, "wrong@example.com")
    assert env.io() == (0, 0, 0)
    assert env.lookup(NUMBER, email_for(NUMBER)).result["status"] == "found"
    assert env.cache.gets == [f"#{NUMBER}"]


def test_a_locked_session_does_no_io_and_adds_no_failures() -> None:
    rig = Rig().build(session=2, ip=9)
    env = Env(rig)
    for _ in range(2):
        env.lookup(NUMBER, "wrong@example.com")
    before = env.io()
    locked = env.lookup(NUMBER, email_for(NUMBER))
    assert locked.result == {"status": "locked"}
    assert env.io() == before
    assert env.view.failures(SESSION) == 2


def test_an_ip_lock_stops_a_fresh_session_with_no_io() -> None:
    rig = Rig().build(session=3, ip=2)
    env = Env(rig)
    for index in range(2):
        env.lookup(NUMBER, "wrong@example.com", session=f"session-{index}")
    before = env.io()
    locked = Env(rig).lookup(NUMBER, email_for(NUMBER), session="fresh")
    assert locked.result == {"status": "locked"}
    assert env.io() == before


@pytest.mark.parametrize("cause", [Cause.NETWORK, Cause.AUTH])
def test_upstream_errors_and_locked_calls_do_not_count_as_failures(cause: Cause) -> None:
    rig = Rig().build(session=2, ip=9)
    env = Env(rig)
    for _ in range(5):
        env.fake.fail("order_state", NotExecuted(cause, "down"))
        assert env.lookup(NUMBER, email_for(NUMBER)).result == {"status": "unavailable"}
    assert env.view.failures(SESSION) == 0
    assert not env.view.is_locked(SESSION)


def test_check_then_record_is_not_atomic_so_the_gate_keeps_one_worker() -> None:
    rig = Rig().build(session=2, ip=9)
    first, second = rig.store.live(IP), rig.store.live(IP)
    first.record_failure(SESSION)
    assert not first.is_locked(SESSION)
    assert not second.is_locked(SESSION)
    first.record_failure(SESSION)
    second.record_failure(SESSION)
    assert rig.store.live(IP).failures(SESSION) == 2


def test_concurrent_failures_are_never_lost() -> None:
    threads, rounds = 8, 300
    rig = Rig().build(session=10**6, ip=10**6, keys=100)

    def work(index: int) -> None:
        view = rig.store.live(IP)
        for _ in range(rounds):
            view.record_failure(f"session-{index}")

    workers = [threading.Thread(target=work, args=(index,)) for index in range(threads)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
    check = rig.store.live(IP)
    assert all(check.failures(f"session-{index}") == rounds for index in range(threads))
    assert check.before().counts[("ip", IP)] == threads * rounds
