import json
from dataclasses import dataclass, field

from tool_support import email_for, harness, shipped_order

from gisting.shopify.results import Uncertain
from gisting.tools.outcomes import MismatchStage
from gisting.tools.trace import internal_json, public_json

MS_PER_SECOND = 1000.0


@dataclass
class TickingClock:
    readings: list[float]
    calls: int = field(default=0, init=False)

    def __call__(self) -> float:
        self.calls += 1
        return self.readings.pop(0)


@dataclass
class ManualClock:
    now: float = 100.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_a_fresh_read_records_wall_clock_milliseconds_from_the_injected_clock() -> None:
    clock = TickingClock([10.0, 10.2505])
    env = harness(shipped_order(1042))
    env.clock = clock
    response = env.lookup("1042", email_for(1042))
    assert response.trace.internal.shopify_ms == 250.5
    assert internal_json(response.trace.internal)["shopify_ms"] == 250.5
    assert clock.calls == 2


def test_a_cache_hit_records_no_shopify_time_and_never_reads_the_clock() -> None:
    clock = TickingClock([10.0, 10.1])
    env = harness(shipped_order(1042))
    env.clock = clock
    env.lookup("1042", email_for(1042))
    again = env.lookup("1042", email_for(1042))
    assert again.trace.internal.cache_hit is True
    assert again.trace.internal.shopify_ms is None
    assert clock.calls == 2


def test_failing_before_the_read_records_no_shopify_time() -> None:
    clock = TickingClock([])
    env = harness(shipped_order(1042))
    env.clock = clock
    for number, email in (("not-an-order", "a@example.com"), ("1042", "wrong@example.com")):
        response = env.lookup(number, email)
        assert response.trace.internal.shopify_ms is None
    assert clock.calls == 0
    assert env.fake.calls == []


def test_a_read_that_finds_nothing_still_records_its_duration() -> None:
    env = harness()
    env.clock = TickingClock([5.0, 5.04])
    response = env.lookup("1042", email_for(1042))
    assert response.trace.internal.result_type == "NotFound"
    assert response.trace.internal.shopify_ms == 40.0


def test_an_upstream_failure_still_records_its_duration() -> None:
    env = harness(shipped_order(1042))
    for _ in range(3):
        env.fake.fail("order_state", Uncertain("tls"))
    env.clock = TickingClock([5.0, 5.5])
    response = env.lookup("1042", email_for(1042))
    assert response.trace.internal.result_type == "UpstreamError"
    assert response.trace.internal.shopify_ms == 500.0


def test_the_duration_includes_the_client_retries() -> None:
    clock = ManualClock()
    env = harness(shipped_order(1042))
    env.clock = clock
    env.sleep = clock.advance
    env.fake.fail("order_state", Uncertain("tls"))
    response = env.lookup("1042", email_for(1042))
    assert response.trace.internal.result_type == "Found"
    assert len(env.fake.calls) == 2
    assert response.trace.internal.shopify_ms == 5.0 * MS_PER_SECOND


def test_the_public_projection_has_no_timing_field() -> None:
    clock = TickingClock([10.0, 10.2])
    env = harness(shipped_order(1042))
    env.clock = clock
    response = env.lookup("1042", email_for(1042))
    public = public_json(response.trace.public)
    assert set(public) == {"tool", "order_number", "outcome"}
    assert "shopify" not in json.dumps(public)


def test_a_non_demo_order_still_records_the_duration_of_its_read() -> None:
    order = shipped_order(1042)
    order.tags = []
    env = harness(order)
    env.clock = TickingClock([2.0, 2.0125])
    response = env.lookup("1042", email_for(1042))
    assert response.trace.internal.result_type == "NotDemoOrder"
    assert response.trace.internal.shopify_ms == 12.5


def test_a_readback_email_mismatch_still_records_the_duration_of_its_read() -> None:
    env = harness(shipped_order(1042, email="someone@orders.example.com"))
    env.clock = TickingClock([3.0, 3.0625])
    response = env.lookup("1042", email_for(1042))
    assert response.trace.internal.result_type == "Mismatch"
    assert response.trace.internal.detail == MismatchStage.READBACK_EMAIL.value
    assert response.trace.internal.shopify_ms == 62.5
