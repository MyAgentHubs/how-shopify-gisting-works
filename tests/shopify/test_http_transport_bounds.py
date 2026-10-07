import time
from collections.abc import Iterator

import pytest
from fakes.http_shopify import Canned, Drip, FakeShopify, Stall, running_shop

from gisting.shopify.graphql import load_document
from gisting.shopify.http_transport import HttpConfig, HttpTransport
from gisting.shopify.http_wire import Clamp
from gisting.shopify.jsonvalue import JsonObject
from gisting.shopify.results import Ok, Uncertain
from gisting.shopify.transport import Request

SECRET = "fake-client-secret-0123456789"
QUERY = Request("order_state", "query { shop { name } }", {})
PACKAGED = Request("order_state", load_document("order_state"), {})
SLOW = 8.0


class Expired(Exception):
    pass


class Sleeps:
    def __init__(self) -> None:
        self.calls: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


@pytest.fixture(autouse=True)
def local_traffic_bypasses_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("no_proxy", "127.0.0.1")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")


@pytest.fixture
def shop() -> Iterator[tuple[FakeShopify, str]]:
    with running_shop() as running:
        yield running


def transport_at(url: str, sleeps: Sleeps, timeout: float = 5.0) -> HttpTransport:
    config = HttpConfig(base_url=url, timeout=timeout, query_attempts=1)
    return HttpTransport(SECRET, config, sleeps)


def capped(limit: float) -> Clamp:
    return lambda wanted: min(wanted, limit)


def until(seconds: float) -> Clamp:
    end = time.monotonic() + seconds

    def clamp(wanted: float) -> float:
        left = end - time.monotonic()
        if left <= 0:
            raise Expired
        return min(wanted, left)

    return clamp


def throttled() -> Canned:
    status: JsonObject = {"maximumAvailable": 1000, "currentlyAvailable": 20, "restoreRate": 50}
    cost: JsonObject = {"requestedQueryCost": 100, "throttleStatus": status}
    return Canned(200, {"data": {"shop": {"name": "fake"}}, "extensions": {"cost": cost}})


def test_a_bounded_view_sleeps_no_longer_than_the_clamp_allows(
    shop: tuple[FakeShopify, str],
) -> None:
    fake, url = shop
    fake.script = [throttled()]
    sleeps = Sleeps()
    transport = transport_at(url, sleeps)
    transport.execute(QUERY)
    transport.bounded(capped(0.3)).execute(QUERY)
    assert sleeps.calls == [0.3]


def test_the_pace_set_by_a_bounded_view_reaches_the_transport_it_came_from(
    shop: tuple[FakeShopify, str],
) -> None:
    fake, url = shop
    fake.script = [throttled()]
    sleeps = Sleeps()
    transport = transport_at(url, sleeps)
    transport.bounded(capped(10.0)).execute(QUERY)
    assert sleeps.calls == []
    transport.execute(QUERY)
    assert sleeps.calls == [1.6]


def test_a_bounded_view_shares_the_token_with_its_origin(shop: tuple[FakeShopify, str]) -> None:
    fake, url = shop
    transport = transport_at(url, Sleeps())
    transport.execute(QUERY)
    transport.bounded(capped(10.0)).execute(QUERY)
    assert len(fake.token_calls) == 1
    assert len(fake.graphql_calls) == 2


def test_an_exhausted_clamp_stops_the_call_before_any_request(
    shop: tuple[FakeShopify, str],
) -> None:
    fake, url = shop

    def exhausted(_wanted: float) -> float:
        raise Expired

    with pytest.raises(Expired):
        transport_at(url, Sleeps()).bounded(exhausted).execute(QUERY)
    assert fake.token_calls == []
    assert fake.graphql_calls == []


def test_a_token_exchange_that_outlives_the_clamp_stops_the_call(
    shop: tuple[FakeShopify, str],
) -> None:
    fake, url = shop
    seen: list[float] = []

    def one_call(wanted: float) -> float:
        seen.append(wanted)
        if len(seen) > 1:
            raise Expired
        return wanted

    with pytest.raises(Expired):
        transport_at(url, Sleeps()).bounded(one_call).execute(QUERY)
    assert len(fake.token_calls) == 1
    assert fake.graphql_calls == []


def test_the_clamp_shortens_the_socket_timeout(shop: tuple[FakeShopify, str]) -> None:
    fake, url = shop
    fake.script = [Stall(SLOW)]
    started = time.monotonic()
    result = transport_at(url, Sleeps()).bounded(capped(0.3)).execute(QUERY)
    assert isinstance(result, Uncertain)
    assert time.monotonic() - started < SLOW / 2


@pytest.mark.parametrize("status", [200, 500])
def test_a_slow_drip_body_is_cut_at_the_deadline(
    shop: tuple[FakeShopify, str], status: int
) -> None:
    fake, url = shop
    fake.script = [Drip(interval=0.1, count=int(SLOW * 10), status=status)]
    started = time.monotonic()
    with pytest.raises(Expired):
        transport_at(url, Sleeps()).bounded(until(0.6)).execute(QUERY)
    assert time.monotonic() - started < SLOW / 2


@pytest.mark.parametrize("bounded", [False, True])
def test_a_truncated_body_is_still_uncertain(shop: tuple[FakeShopify, str], bounded: bool) -> None:
    fake, url = shop
    fake.script = [Drip(interval=0.0, count=3, declared=50)]
    transport = transport_at(url, Sleeps())
    result = (transport.bounded(capped(10.0)) if bounded else transport).execute(QUERY)
    assert isinstance(result, Uncertain)
    assert "IncompleteRead" in result.reason


@pytest.mark.parametrize("status", [200, 500])
def test_every_chunk_of_a_body_asks_the_clamp(shop: tuple[FakeShopify, str], status: int) -> None:
    fake, url = shop
    fake.script = [Drip(interval=0.01, count=20, status=status)]
    asked: list[float] = []

    def clamp(wanted: float) -> float:
        asked.append(wanted)
        if len(asked) > 4:
            raise Expired
        return wanted

    with pytest.raises(Expired):
        transport_at(url, Sleeps()).bounded(clamp).execute(QUERY)
    assert fake.graphql_calls


def test_the_retry_sleep_is_clamped(shop: tuple[FakeShopify, str]) -> None:
    fake, url = shop
    fake.script = [Canned(500, raw=b"boom"), Canned()]
    sleeps = Sleeps()
    config = HttpConfig(base_url=url, timeout=5.0, query_attempts=2, backoff_seconds=1.0)
    result = HttpTransport(SECRET, config, sleeps).bounded(capped(0.3)).execute(PACKAGED)
    assert isinstance(result, Ok)
    assert sleeps.calls == [0.3]


def owing_forty_seconds() -> Canned:
    status: JsonObject = {"maximumAvailable": 1000, "currentlyAvailable": 0, "restoreRate": 50}
    cost: JsonObject = {"requestedQueryCost": 2000, "throttleStatus": status}
    return Canned(200, {"data": {"shop": {"name": "fake"}}, "extensions": {"cost": cost}})


def spent_after_the_first_wait(first: float) -> Clamp:
    asked: list[float] = []

    def clamp(wanted: float) -> float:
        asked.append(wanted)
        if len(asked) > 1:
            raise Expired
        return min(wanted, first)

    return clamp


def test_a_pause_cut_short_by_a_deadline_is_still_owed_to_the_next_request(
    shop: tuple[FakeShopify, str],
) -> None:
    fake, url = shop
    fake.script = [owing_forty_seconds()]
    sleeps = Sleeps()
    config = HttpConfig(base_url=url, timeout=5.0, query_attempts=1, max_wait_seconds=60.0)
    transport = HttpTransport(SECRET, config, sleeps)
    transport.bounded(capped(20.0)).execute(QUERY)
    with pytest.raises(Expired):
        transport.bounded(spent_after_the_first_wait(0.5)).execute(QUERY)
    transport.bounded(capped(20.0)).execute(QUERY)
    assert sleeps.calls == [0.5, 20.0]


def test_a_pause_longer_than_the_cap_is_spent_by_one_full_sleep(
    shop: tuple[FakeShopify, str],
) -> None:
    fake, url = shop
    fake.script = [owing_forty_seconds()]
    sleeps = Sleeps()
    config = HttpConfig(base_url=url, timeout=5.0, query_attempts=1, max_wait_seconds=2.0)
    transport = HttpTransport(SECRET, config, sleeps)
    transport.bounded(capped(20.0)).execute(QUERY)
    with pytest.raises(Expired):
        transport.bounded(spent_after_the_first_wait(20.0)).execute(QUERY)
    transport.bounded(capped(20.0)).execute(QUERY)
    assert sleeps.calls == [2.0]
