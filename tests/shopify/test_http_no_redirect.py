from collections.abc import Iterator

import pytest
from fakes.http_shopify import Canned, FakeShopify, running_shop

from gisting.shopify.graphql import load_document
from gisting.shopify.http_transport import HttpConfig, HttpTransport
from gisting.shopify.results import Cause, NotExecuted
from gisting.shopify.transport import Request

SECRET = "fake-client-secret-0123456789"
QUERY = Request("order_state", load_document("order_state"), {})
MUTATION = Request("tags_add", load_document("tags_add"), {})
REDIRECTS = [301, 302, 303, 307, 308]


@pytest.fixture(autouse=True)
def local_traffic_bypasses_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("no_proxy", "127.0.0.1")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")


@pytest.fixture
def two_hosts() -> Iterator[tuple[FakeShopify, str, FakeShopify, str]]:
    with running_shop() as (admin, admin_url), running_shop() as (other, other_url):
        yield admin, admin_url, other, other_url


def redirecting(admin: FakeShopify, other_url: str, status: int, count: int) -> None:
    location = {"Location": f"{other_url}/admin/api/x/graphql.json"}
    admin.script = [Canned(status=status, headers=location) for _ in range(count)]


def transport_at(url: str) -> HttpTransport:
    config = HttpConfig(base_url=url, timeout=5.0, backoff_seconds=0.0)
    return HttpTransport(SECRET, config, lambda _seconds: None)


@pytest.mark.parametrize("status", REDIRECTS)
def test_a_redirect_on_a_read_is_an_upstream_error_and_the_other_host_sees_nothing(
    two_hosts: tuple[FakeShopify, str, FakeShopify, str], status: int
) -> None:
    admin, admin_url, other, other_url = two_hosts
    redirecting(admin, other_url, status, 3)
    result = transport_at(admin_url).execute(QUERY)
    assert isinstance(result, NotExecuted)
    assert result.cause is Cause.HTTP_STATUS
    assert other.graphql_calls == []
    assert other.token_calls == []
    assert len(admin.graphql_calls) == 1


@pytest.mark.parametrize("status", REDIRECTS)
def test_a_redirect_on_a_write_is_not_executed_not_retried_and_the_token_stays_home(
    two_hosts: tuple[FakeShopify, str, FakeShopify, str], status: int
) -> None:
    admin, admin_url, other, other_url = two_hosts
    redirecting(admin, other_url, status, 3)
    result = transport_at(admin_url).execute(MUTATION)
    assert isinstance(result, NotExecuted)
    assert result.cause is Cause.HTTP_STATUS
    assert other.graphql_calls == []
    assert other.token_calls == []
    assert len(admin.graphql_calls) == 1
