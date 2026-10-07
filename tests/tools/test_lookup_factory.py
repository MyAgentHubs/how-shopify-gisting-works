from fakes.shopify import FakeTransport
from tool_support import POLICY, SECRET, SESSION, SpyCache, email_for, shipped_order

from gisting.shopify.client import AdminClient
from gisting.shopify.jsonvalue import JsonObject
from gisting.shopify.order_state import OrderState
from gisting.tools.attempts import InMemoryFailureCounter
from gisting.tools.cache import InMemoryOrderCache
from gisting.tools.factory import build_lookup
from gisting.tools.lookup_order import LookupOrder


class LockedCounter:
    def __init__(self) -> None:
        self.recorded: list[str] = []

    def failures(self, session_id: str) -> int:
        return 0

    def is_locked(self, session_id: str) -> bool:
        return session_id == SESSION

    def record_failure(self, session_id: str) -> None:
        self.recorded.append(session_id)


def tool_with(counter: LockedCounter) -> LookupOrder:
    client = AdminClient(FakeTransport([shipped_order(1042)]), sleep=lambda _seconds: None)
    return build_lookup(client, InMemoryOrderCache(60), counter, POLICY, SECRET)


def test_factory_uses_the_injected_failure_counter_to_lock_a_session() -> None:
    tool = tool_with(LockedCounter())
    arguments: JsonObject = {"order_number": "1042", "email": email_for(1042)}
    assert tool.call(arguments, SESSION).result == {"status": "locked"}
    assert tool.call(arguments, "other").result["status"] == "found"


def test_factory_records_failures_on_the_injected_failure_counter() -> None:
    counter = LockedCounter()
    tool_with(counter).call({"order_number": "1042", "email": "wrong@example.com"}, "fresh")
    assert counter.recorded == ["fresh"]


class RecordingCache:
    def __init__(self) -> None:
        self.gets: list[str] = []
        self.puts: list[str] = []
        self.inner = InMemoryOrderCache(60)

    def get(self, order_name: str) -> OrderState | None:
        self.gets.append(order_name)
        return self.inner.get(order_name)

    def put(self, order_name: str, order: OrderState) -> None:
        self.puts.append(order_name)
        self.inner.put(order_name, order)


def test_factory_reads_and_fills_the_injected_cache() -> None:
    cache = RecordingCache()
    client = AdminClient(FakeTransport([shipped_order(1042)]), sleep=lambda _seconds: None)
    tool = build_lookup(client, cache, InMemoryFailureCounter(POLICY.failure_limit), POLICY, SECRET)
    arguments: JsonObject = {"order_number": "1042", "email": email_for(1042)}
    assert tool.call(arguments, SESSION).result["status"] == "found"
    assert (cache.gets, cache.puts) == (["#1042"], ["#1042"])


def test_factory_locks_by_the_injected_counters_limit_not_the_policys() -> None:
    wrong: JsonObject = {"order_number": "1042", "email": "wrong@example.com"}
    right: JsonObject = {"order_number": "1042", "email": email_for(1042)}
    client = AdminClient(FakeTransport([shipped_order(1042)]), sleep=lambda _seconds: None)
    counter = InMemoryFailureCounter(limit=1)
    assert POLICY.failure_limit > 1
    tool = build_lookup(client, InMemoryOrderCache(60), counter, POLICY, SECRET)
    tool.call(wrong, SESSION)
    assert tool.call(right, SESSION).result == {"status": "locked"}


class AlwaysLocked:
    def __init__(self) -> None:
        self.recorded: list[str] = []

    def failures(self, session_id: str) -> int:
        return 0

    def is_locked(self, session_id: str) -> bool:
        return True

    def record_failure(self, session_id: str) -> None:
        self.recorded.append(session_id)


def test_a_locked_counter_stops_all_io_and_records_no_failure() -> None:
    cache, counter, fake = SpyCache(), AlwaysLocked(), FakeTransport([shipped_order(1042)])
    client = AdminClient(fake, sleep=lambda _seconds: None)
    tool = build_lookup(client, cache, counter, POLICY, SECRET)
    arguments: JsonObject = {"order_number": "1042", "email": email_for(1042)}
    response = tool.call(arguments, SESSION)
    assert response.result == {"status": "locked"}
    assert (cache.gets, cache.puts, fake.calls, counter.recorded) == ([], [], [], [])
