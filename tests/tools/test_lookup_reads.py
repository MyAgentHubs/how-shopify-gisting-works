import pytest
from tool_support import SESSION, SpyCache, SpyCounter, email_for, harness, shipped_order

from gisting.shopify.order_state import OrderState
from gisting.tools.reads import DISCARD, LookupRead


class Collecting:
    def __init__(self) -> None:
        self.items: list[LookupRead] = []
        self.interrupted: list[str] = []
        self.begun = 0

    def begin(self) -> "Collecting":
        self.begun += 1
        return self

    def finish(self, read: LookupRead) -> None:
        self.items.append(read)

    def interrupt(self, error_type: str) -> None:
        self.interrupted.append(error_type)


def test_a_fresh_read_is_reported_with_its_duration_and_cache_miss() -> None:
    sink = Collecting()
    env = harness(shipped_order(1042))
    env.reads = sink
    env.clock = iter([10.0, 10.2505]).__next__
    env.lookup("1042", email_for(1042))
    assert sink.items == [LookupRead(250.5, "Found", False)]


def test_a_cache_hit_is_reported_without_a_duration() -> None:
    sink = Collecting()
    env = harness(shipped_order(1042))
    env.reads = sink
    env.lookup("1042", email_for(1042))
    env.lookup("1042", email_for(1042))
    assert [(read.result_type, read.cache_hit) for read in sink.items] == [
        ("Found", False),
        ("Found", True),
    ]
    assert sink.items[1].shopify_ms is None


def test_failures_before_the_read_are_reported_with_neither_duration_nor_cache_state() -> None:
    sink = Collecting()
    env = harness(shipped_order(1042))
    env.reads = sink
    env.lookup("not-an-order", "a@example.com")
    env.lookup("1042", "wrong@example.com")
    assert sink.items == [
        LookupRead(None, "Malformed", None),
        LookupRead(None, "Mismatch", None),
    ]


def test_a_locked_session_is_reported_as_locked() -> None:
    sink = Collecting()
    env = harness(shipped_order(1042))
    env.reads = sink
    env.attempts = SpyCounter(1)
    env.lookup("1042", "wrong@example.com")
    env.lookup("1042", email_for(1042))
    assert [read.result_type for read in sink.items] == ["Mismatch", "Locked"]


def test_the_reported_read_matches_the_internal_trace() -> None:
    sink = Collecting()
    env = harness(shipped_order(1042))
    env.reads = sink
    trace = env.lookup("1042", email_for(1042)).trace.internal
    assert sink.items == [LookupRead(trace.shopify_ms, trace.result_type, trace.cache_hit)]


def test_the_default_sink_discards_without_error() -> None:
    env = harness(shipped_order(1042))
    assert env.reads is DISCARD
    assert env.lookup("1042", email_for(1042)).result["status"]


class Interrupted(Exception):
    pass


class ExplodingCache(SpyCache):
    def get(self, order_name: str) -> OrderState | None:
        raise Interrupted


def test_an_error_inside_the_lookup_is_reported_as_interrupted_and_still_raised() -> None:
    sink = Collecting()
    env = harness(shipped_order(1042))
    env.reads = sink

    env.cache = ExplodingCache()
    with pytest.raises(Interrupted):
        env.lookup("1042", email_for(1042))
    assert (sink.begun, sink.items, sink.interrupted) == (1, [], ["Interrupted"])


def test_an_interrupted_lookup_does_not_count_as_a_failed_attempt() -> None:
    env = harness(shipped_order(1042))
    env.reads = Collecting()

    env.cache = ExplodingCache()
    with pytest.raises(Interrupted):
        env.lookup("1042", email_for(1042))
    assert env.attempts.failures(SESSION) == 0


class Aborted(BaseException):
    pass


class AbortingCache(SpyCache):
    def get(self, order_name: str) -> OrderState | None:
        raise Aborted


def test_an_error_outside_exception_is_reported_by_its_class_and_still_raised() -> None:
    sink = Collecting()
    env = harness(shipped_order(1042))
    env.reads = sink
    env.cache = AbortingCache()
    with pytest.raises(Aborted):
        env.lookup("1042", email_for(1042))
    assert (sink.begun, sink.items, sink.interrupted) == (1, [], ["Aborted"])
