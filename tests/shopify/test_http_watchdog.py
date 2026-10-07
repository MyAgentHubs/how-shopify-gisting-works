import os
import socket
import ssl
import threading
import time
import urllib.request
from collections.abc import Callable, Iterator
from contextlib import closing

import pytest
from fakes.http_shopify import Canned, Drip, Drop, FakeShopify, running_shop

from gisting.shopify.http_transport import HttpConfig, HttpTransport
from gisting.shopify.http_wire import Clamp, Reply, send
from gisting.shopify.results import Ok, Uncertain
from gisting.shopify.transport import Request

SECRET = "fake-client-secret-0123456789"
QUERY = Request("order_state", "query { shop { name } }", {})
DEADLINE = 5.0
SOCKET_TIMEOUT = 6.0
SLACK = 0.5


class Expired(Exception):
    pass


@pytest.fixture(autouse=True)
def local_traffic_bypasses_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("no_proxy", "127.0.0.1")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")


@pytest.fixture
def shop() -> Iterator[tuple[FakeShopify, str]]:
    with running_shop() as running:
        yield running


def until(seconds: float) -> Clamp:
    end = time.monotonic() + seconds

    def clamp(wanted: float) -> float:
        left = end - time.monotonic()
        if left <= 0:
            raise Expired
        return min(wanted, left)

    return clamp


def transport_at(url: str) -> HttpTransport:
    config = HttpConfig(base_url=url, timeout=SOCKET_TIMEOUT, query_attempts=1)
    return HttpTransport(SECRET, config, lambda _seconds: None)


def authorized_post(fake: FakeShopify, url: str) -> urllib.request.Request:
    return urllib.request.Request(
        f"{url}/admin/api/x/graphql.json",
        data=b"{}",
        headers={"X-Shopify-Access-Token": fake.issue()},
        method="POST",
    )


def watchdog_timers() -> int:
    return sum(isinstance(thread, threading.Timer) for thread in threading.enumerate())


def test_a_server_dripping_header_lines_is_cut_at_the_deadline(
    shop: tuple[FakeShopify, str],
) -> None:
    fake, url = shop
    fake.script = [Drip(interval=3.0, count=10, in_headers=True)]
    started = time.monotonic()
    with pytest.raises(Expired):
        transport_at(url).bounded(until(DEADLINE)).execute(QUERY)
    assert time.monotonic() - started < DEADLINE + SLACK
    assert watchdog_timers() == 0


def test_a_server_dripping_the_body_slower_than_the_socket_timeout_is_cut_at_the_deadline(
    shop: tuple[FakeShopify, str],
) -> None:
    fake, url = shop
    fake.script = [Drip(interval=4.5, count=10, declared=100)]
    started = time.monotonic()
    with pytest.raises(Expired):
        transport_at(url).bounded(until(DEADLINE)).execute(QUERY)
    assert time.monotonic() - started < DEADLINE + SLACK
    assert watchdog_timers() == 0


def test_a_tls_handshake_that_never_answers_is_cut_at_the_deadline() -> None:
    with closing(socket.socket()) as silent:
        silent.bind(("127.0.0.1", 0))
        silent.listen()
        request = urllib.request.Request(f"https://127.0.0.1:{silent.getsockname()[1]}")
        started = time.monotonic()
        with pytest.raises(Expired):
            send(request, SOCKET_TIMEOUT, until(1.0))
    assert time.monotonic() - started < 1.0 + SLACK
    assert watchdog_timers() == 0


def test_a_deadline_that_passes_without_the_clamp_noticing_is_uncertain(
    shop: tuple[FakeShopify, str],
) -> None:
    fake, url = shop
    fake.script = [Drip(interval=0.2, count=50, in_headers=True)]
    asked: list[float] = []

    def clamp(wanted: float) -> float:
        asked.append(wanted)
        return 0.5 if len(asked) == 1 else wanted

    started = time.monotonic()
    outcome = send(authorized_post(fake, url), SOCKET_TIMEOUT, clamp)
    assert isinstance(outcome, Uncertain)
    assert time.monotonic() - started < 0.5 + SLACK


def test_a_failure_after_the_deadline_is_the_deadline(shop: tuple[FakeShopify, str]) -> None:
    fake, url = shop
    fake.script = [Drop()]
    asked: list[float] = []

    def clamp(wanted: float) -> float:
        asked.append(wanted)
        if len(asked) > 1:
            raise Expired
        return wanted

    with pytest.raises(Expired):
        send(authorized_post(fake, url), SOCKET_TIMEOUT, clamp)


def test_a_header_drip_over_https_is_cut_at_the_deadline(
    shop: tuple[FakeShopify, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    fake, url = shop
    fake.script = [Drip(interval=0.3, count=50, in_headers=True)]
    port = int(url.rsplit(":", 1)[1])
    real_connect = socket.create_connection

    def to_the_fake(
        _address: object, timeout: float | None = None, source: tuple[str, int] | None = None
    ) -> socket.socket:
        return real_connect(("127.0.0.1", port), timeout, source)

    def without_tls(
        _context: ssl.SSLContext, sock: socket.socket, **_kwargs: object
    ) -> socket.socket:
        return sock

    monkeypatch.setenv("no_proxy", "*")
    monkeypatch.setenv("NO_PROXY", "*")
    monkeypatch.setattr(socket, "create_connection", to_the_fake)
    monkeypatch.setattr(ssl.SSLContext, "wrap_socket", without_tls)
    request = authorized_post(fake, "https://shop.test")
    started = time.monotonic()
    with pytest.raises(Expired):
        send(request, SOCKET_TIMEOUT, until(1.0))
    assert time.monotonic() - started < 1.5
    assert watchdog_timers() == 0


def test_an_exchange_longer_than_the_socket_timeout_but_inside_the_deadline_succeeds(
    shop: tuple[FakeShopify, str],
) -> None:
    fake, url = shop
    fake.script = [Drip(interval=0.2, count=5, in_headers=True)]
    started = time.monotonic()
    outcome = send(authorized_post(fake, url), 0.3, until(3.0))
    assert isinstance(outcome, Reply)
    assert outcome.status == 200
    assert time.monotonic() - started > 0.9
    assert watchdog_timers() == 0


def test_the_connect_is_given_no_more_time_than_the_deadline_has_left(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    given: list[float | None] = []

    def refuse(
        _address: object, timeout: float | None = None, _source: object = None
    ) -> socket.socket:
        given.append(timeout)
        raise ConnectionRefusedError

    monkeypatch.setattr(socket, "create_connection", refuse)
    send(urllib.request.Request("http://127.0.0.1:9"), SOCKET_TIMEOUT, until(0.5))
    assert len(given) == 1
    assert given[0] is not None
    assert given[0] <= 0.5


def open_descriptors() -> int:
    return len(os.listdir("/dev/fd"))


def settled(count: Callable[[], int], expected: int) -> int:
    deadline = time.monotonic() + 2.0
    while count() > expected and time.monotonic() < deadline:
        time.sleep(0.01)
    return count()


def test_a_normal_exchange_is_untouched_and_leaves_no_watchdog_behind(
    shop: tuple[FakeShopify, str],
) -> None:
    fake, url = shop
    fake.script = [Canned(), Canned()]
    threads = threading.active_count()
    descriptors = open_descriptors()
    bounded = transport_at(url).bounded(until(DEADLINE))
    assert isinstance(bounded.execute(QUERY), Ok)
    assert isinstance(bounded.execute(QUERY), Ok)
    assert watchdog_timers() == 0
    assert settled(threading.active_count, threads) == threads
    assert settled(open_descriptors, descriptors) == descriptors


def test_a_cut_exchange_leaves_no_descriptor_behind(shop: tuple[FakeShopify, str]) -> None:
    fake, url = shop
    fake.script = [Drip(interval=0.2, count=50, in_headers=True)]
    descriptors = open_descriptors()
    with pytest.raises(Expired):
        transport_at(url).bounded(until(0.5)).execute(QUERY)
    assert settled(open_descriptors, descriptors) == descriptors


def test_an_unbounded_exchange_starts_no_watchdog(shop: tuple[FakeShopify, str]) -> None:
    fake, url = shop
    outcome = send(authorized_post(fake, url), SOCKET_TIMEOUT)
    assert isinstance(outcome, Reply)
    assert watchdog_timers() == 0
