import json
import socket
import ssl
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import closing

import pytest
from fakes.http_shopify import Canned, Drop, FakeShopify, Stall, Step, form_fields, running_shop

from gisting.shopify.graphql import load_document
from gisting.shopify.http_transport import HttpConfig, HttpTransport
from gisting.shopify.http_wire import send
from gisting.shopify.jsonvalue import JsonObject
from gisting.shopify.results import Cause, GraphQLError, NotExecuted, Ok, Result, Uncertain
from gisting.shopify.target import API_VERSION, CLIENT_ID, DEV_STORE, StoreNotAllowed
from gisting.shopify.transport import Request

SECRET = "fake-client-secret-0123456789"
QUERY = Request("order_state", load_document("order_state"), {})
MUTATION = Request("tags_add", load_document("tags_add"), {})


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


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


def make(
    base_url: str, sleeps: Sleeps, clock: Clock | None = None, timeout: float = 5.0
) -> HttpTransport:
    config = HttpConfig(base_url=base_url, timeout=timeout)
    return HttpTransport(SECRET, config, sleeps, clock or Clock())


def test_token_is_requested_with_client_credentials(shop: tuple[FakeShopify, str]) -> None:
    fake, url = shop
    assert make(url, Sleeps()).execute(QUERY) == Ok({"shop": {"name": "fake"}})
    call = fake.token_calls[0]
    assert call.headers["Content-Type"] == "application/x-www-form-urlencoded"
    assert form_fields(call.body) == {
        "grant_type": "client_credentials",
        "client_id": CLIENT_ID,
        "client_secret": SECRET,
    }
    graphql = fake.graphql_calls[0]
    assert graphql.path == f"/admin/api/{API_VERSION}/graphql.json"
    assert graphql.headers["X-Shopify-Access-Token"] == fake.valid_token
    assert json.loads(graphql.body)["query"] == QUERY.document


def test_token_is_cached_between_requests(shop: tuple[FakeShopify, str]) -> None:
    fake, url = shop
    transport = make(url, Sleeps())
    for _ in range(3):
        assert isinstance(transport.execute(QUERY), Ok)
    assert len(fake.token_calls) == 1


def test_token_refreshes_sixty_seconds_before_expiry() -> None:
    clock = Clock()
    with running_shop(expires_in=100) as (fake, url):
        transport = make(url, Sleeps(), clock)
        transport.execute(QUERY)
        clock.now += 39
        transport.execute(QUERY)
        assert len(fake.token_calls) == 1
        clock.now += 2
        transport.execute(QUERY)
        assert len(fake.token_calls) == 2
        assert fake.graphql_calls[-1].headers["X-Shopify-Access-Token"] == "fake-token-2"


def test_401_discards_token_and_exchanges_once_more(shop: tuple[FakeShopify, str]) -> None:
    fake, url = shop
    transport = make(url, Sleeps())
    transport.execute(QUERY)
    fake.revoke()
    assert isinstance(transport.execute(MUTATION), Ok)
    assert len(fake.token_calls) == 2
    assert len(fake.graphql_calls) == 3


def test_persistent_401_gives_up_after_one_reexchange(shop: tuple[FakeShopify, str]) -> None:
    fake, url = shop
    fake.reject_all = True
    result = make(url, Sleeps()).execute(MUTATION)
    assert isinstance(result, NotExecuted)
    assert result.cause is Cause.AUTH
    assert len(fake.token_calls) == 2
    assert len(fake.graphql_calls) == 2


def test_failed_token_exchange_sends_no_graphql_and_hides_secret(
    shop: tuple[FakeShopify, str],
) -> None:
    fake, url = shop
    fake.token_status = 401
    result = make(url, Sleeps()).execute(MUTATION)
    assert isinstance(result, NotExecuted)
    assert result.cause is Cause.AUTH
    assert fake.graphql_calls == []
    assert SECRET not in result.detail


def closed_port_url() -> str:
    with closing(socket.socket()) as probe:
        probe.bind(("127.0.0.1", 0))
        return f"http://127.0.0.1:{probe.getsockname()[1]}"


def test_connection_refused_is_not_executed_and_query_is_retried() -> None:
    sleeps = Sleeps()
    result = make(closed_port_url(), sleeps).execute(QUERY)
    assert isinstance(result, NotExecuted)
    assert result.cause is Cause.NETWORK
    assert sleeps.calls == [1.0, 2.0]


def test_connection_refused_on_mutation_is_not_retried() -> None:
    sleeps = Sleeps()
    result = make(closed_port_url(), sleeps).execute(MUTATION)
    assert isinstance(result, NotExecuted)
    assert sleeps.calls == []


def test_dropped_query_is_uncertain_and_retried_three_times(
    shop: tuple[FakeShopify, str],
) -> None:
    fake, url = shop
    fake.script = [Drop(), Drop(), Drop()]
    sleeps = Sleeps()
    assert isinstance(make(url, sleeps).execute(QUERY), Uncertain)
    assert len(fake.graphql_calls) == 3
    assert sleeps.calls == [1.0, 2.0]


def test_dropped_mutation_is_uncertain_and_never_retried(shop: tuple[FakeShopify, str]) -> None:
    fake, url = shop
    fake.script = [Drop()]
    sleeps = Sleeps()
    assert isinstance(make(url, sleeps).execute(MUTATION), Uncertain)
    assert len(fake.graphql_calls) == 1
    assert sleeps.calls == []


def test_timeout_after_send_is_uncertain(shop: tuple[FakeShopify, str]) -> None:
    fake, url = shop
    fake.script = [Stall(1.0)]
    assert isinstance(make(url, Sleeps(), timeout=0.2).execute(MUTATION), Uncertain)


def test_server_error_is_uncertain_for_mutation_and_retried_for_query(
    shop: tuple[FakeShopify, str],
) -> None:
    fake, url = shop
    fake.script = [Canned(502, raw=b"bad gateway"), Canned()]
    assert isinstance(make(url, Sleeps()).execute(MUTATION), Uncertain)
    assert len(fake.graphql_calls) == 1
    fake.script = [Canned(503, raw=b"busy"), Canned()]
    assert isinstance(make(url, Sleeps()).execute(QUERY), Ok)


def test_429_query_waits_retry_after_then_succeeds(shop: tuple[FakeShopify, str]) -> None:
    fake, url = shop
    fake.script = [Canned(429, {}, {"Retry-After": "2"}), Canned()]
    sleeps = Sleeps()
    assert isinstance(make(url, sleeps).execute(QUERY), Ok)
    assert sleeps.calls == [2.0]
    assert len(fake.graphql_calls) == 2


def test_429_mutation_is_not_executed_and_not_retried(shop: tuple[FakeShopify, str]) -> None:
    fake, url = shop
    fake.script = [Canned(429, {}, {"Retry-After": "7"}), Canned()]
    sleeps = Sleeps()
    result = make(url, sleeps).execute(MUTATION)
    assert result == NotExecuted(Cause.RATE_LIMITED, "retry-after 7s")
    assert len(fake.graphql_calls) == 1
    assert sleeps.calls == []


def test_429_without_header_falls_back_to_backoff(shop: tuple[FakeShopify, str]) -> None:
    fake, url = shop
    fake.script = [Canned(429), Canned()]
    sleeps = Sleeps()
    assert isinstance(make(url, sleeps).execute(QUERY), Ok)
    assert sleeps.calls == [1.0]


def test_graphql_errors_map_to_graphql_error_without_retry(shop: tuple[FakeShopify, str]) -> None:
    fake, url = shop
    fake.script = [Canned(200, {"errors": [{"message": "denied"}]})]
    sleeps = Sleeps()
    result = make(url, sleeps).execute(QUERY)
    assert result == GraphQLError(({"message": "denied"},))
    assert len(fake.graphql_calls) == 1


def test_throttled_graphql_error_is_retried_for_queries(shop: tuple[FakeShopify, str]) -> None:
    fake, url = shop
    throttled: JsonObject = {
        "errors": [{"message": "Throttled", "extensions": {"code": "THROTTLED"}}]
    }
    script: list[Step] = [Canned(200, throttled), Canned()]
    fake.script = script
    sleeps = Sleeps()
    assert isinstance(make(url, sleeps).execute(QUERY), Ok)
    assert sleeps.calls == [1.0]


def test_unreadable_200_is_uncertain_and_other_4xx_is_not_executed(
    shop: tuple[FakeShopify, str],
) -> None:
    fake, url = shop
    fake.script = [Canned(200, raw=b"<html>")]
    assert isinstance(make(url, Sleeps()).execute(MUTATION), Uncertain)
    fake.script = [Canned(403, raw=b"forbidden")]
    result = make(url, Sleeps()).execute(MUTATION)
    assert isinstance(result, NotExecuted)
    assert result.cause is Cause.HTTP_STATUS


def throttle_body(available: int, cost: int = 100) -> JsonObject:
    status: JsonObject = {
        "maximumAvailable": 1000,
        "currentlyAvailable": available,
        "restoreRate": 50,
    }
    return {
        "data": {"shop": {"name": "fake"}},
        "extensions": {"cost": {"requestedQueryCost": cost, "throttleStatus": status}},
    }


def test_throttle_status_is_recorded_and_low_budget_paces_next_request(
    shop: tuple[FakeShopify, str],
) -> None:
    fake, url = shop
    fake.script = [Canned(200, throttle_body(20))]
    sleeps = Sleeps()
    transport = make(url, sleeps)
    result = transport.execute(QUERY)
    assert isinstance(result, Ok)
    assert result.throttle == {
        "maximumAvailable": 1000,
        "currentlyAvailable": 20,
        "restoreRate": 50,
    }
    assert sleeps.calls == []
    transport.execute(QUERY)
    assert sleeps.calls == [1.6]


def test_error_details_and_stderr_never_contain_secret_or_token(
    shop: tuple[FakeShopify, str], capsys: pytest.CaptureFixture[str]
) -> None:
    fake, url = shop
    transport = make(url, Sleeps())
    transport.execute(QUERY)
    token = fake.valid_token
    fake.script = [Canned(403, raw=f"echo {token} and {SECRET}".encode())]
    result = transport.execute(MUTATION)
    assert isinstance(result, NotExecuted)
    assert token not in result.detail
    assert SECRET not in result.detail
    assert "***" in result.detail
    fake.token_status = 500
    fake.revoke()
    failed = transport.execute(MUTATION)
    assert SECRET not in repr(failed)
    captured = capsys.readouterr()
    assert SECRET not in captured.err + captured.out
    assert token not in captured.err + captured.out


def test_wrong_store_is_refused() -> None:
    with pytest.raises(StoreNotAllowed):
        HttpTransport(SECRET, HttpConfig(store="other.myshopify.com"))


def test_default_target_is_the_dev_store() -> None:
    assert HttpTransport(SECRET).store == DEV_STORE


def fail_with(monkeypatch: pytest.MonkeyPatch, error: Exception) -> None:
    def refuse(*_args: object, **_kwargs: object) -> None:
        raise error

    monkeypatch.setattr(urllib.request.OpenerDirector, "open", refuse)


def probe() -> Result | object:
    return send(urllib.request.Request("http://example.invalid"), 1.0)


@pytest.mark.parametrize(
    "reason",
    [socket.gaierror("no such host"), ConnectionRefusedError(), ssl.SSLCertVerificationError()],
)
def test_failures_before_the_connection_exists_are_not_executed(
    monkeypatch: pytest.MonkeyPatch, reason: OSError
) -> None:
    fail_with(monkeypatch, urllib.error.URLError(reason))
    assert isinstance(probe(), NotExecuted)


@pytest.mark.parametrize(
    "error",
    [
        urllib.error.URLError(ssl.SSLError("handshake")),
        urllib.error.URLError(TimeoutError()),
        urllib.error.URLError(ConnectionResetError()),
        ConnectionResetError(),
        TimeoutError(),
    ],
)
def test_anything_else_is_uncertain(monkeypatch: pytest.MonkeyPatch, error: Exception) -> None:
    fail_with(monkeypatch, error)
    assert isinstance(probe(), Uncertain)
