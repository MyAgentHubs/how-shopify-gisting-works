from collections.abc import Iterator

import pytest
from fakes.http_shopify import Canned, Drop, FakeShopify, running_shop

from gisting.shopify.graphql import load_document
from gisting.shopify.http_transport import HttpConfig, HttpTransport
from gisting.shopify.results import Ok, Uncertain
from gisting.shopify.transport import Request

TAGS_ADD = load_document("tags_add")
QUERY = Request("order_state", load_document("order_state"), {})
DISGUISED = {
    "comment first": "# c\n" + TAGS_ADD,
    "byte order mark first": "﻿" + TAGS_ADD,
    "comma first": "," + TAGS_ADD,
    "fragment first": "fragment F on Order { id }\n" + TAGS_ADD,
}


@pytest.fixture(autouse=True)
def local_traffic_bypasses_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("no_proxy", "127.0.0.1")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")


@pytest.fixture
def shop() -> Iterator[tuple[FakeShopify, str]]:
    with running_shop() as running:
        yield running


class Sleeps:
    def __init__(self) -> None:
        self.calls: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


def transport(url: str, sleeps: Sleeps) -> HttpTransport:
    return HttpTransport("fake-client-secret-0123456789", HttpConfig(base_url=url), sleeps)


@pytest.mark.parametrize("document", DISGUISED.values(), ids=DISGUISED.keys())
def test_a_disguised_mutation_is_never_retried(
    shop: tuple[FakeShopify, str], document: str
) -> None:
    fake, url = shop
    fake.script = [Drop(), Drop(), Drop()]
    sleeps = Sleeps()
    result = transport(url, sleeps).execute(Request("tags_add", document, {}))
    assert isinstance(result, Uncertain)
    assert len(fake.graphql_calls) == 1
    assert sleeps.calls == []


def test_a_document_that_is_not_the_packaged_query_is_never_retried(
    shop: tuple[FakeShopify, str],
) -> None:
    fake, url = shop
    fake.script = [Canned(503, raw=b"busy"), Canned()]
    result = transport(url, Sleeps()).execute(Request("order_state", "query { x }", {}))
    assert isinstance(result, Uncertain)
    assert len(fake.graphql_calls) == 1


def test_the_packaged_query_is_retried(shop: tuple[FakeShopify, str]) -> None:
    fake, url = shop
    fake.script = [Canned(503, raw=b"busy"), Canned()]
    assert isinstance(transport(url, Sleeps()).execute(QUERY), Ok)
    assert len(fake.graphql_calls) == 2
