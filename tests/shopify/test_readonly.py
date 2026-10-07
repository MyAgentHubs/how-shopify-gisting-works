import pytest

from gisting.shopify.graphql import load_document
from gisting.shopify.readonly import ReadOnlyTransport
from gisting.shopify.results import Cause, NotExecuted, Ok, Result
from gisting.shopify.target import DEV_STORE
from gisting.shopify.transport import Request

TAGS_ADD = load_document("tags_add")
ORDER_STATE = load_document("order_state")


class Recording:
    store = DEV_STORE

    def __init__(self) -> None:
        self.calls: list[Request] = []

    def execute(self, request: Request) -> Result:
        self.calls.append(request)
        return Ok({})


BYPASSES = {
    "comment first": "# c\n" + TAGS_ADD,
    "byte order mark first": "﻿" + TAGS_ADD,
    "comma first": "," + TAGS_ADD,
    "fragment first": "fragment F on Order { id }\n" + TAGS_ADD,
    "anonymous mutation": "{ x }\nmutation { x }",
    "query keyword then mutation": "query Q { shop { name } }\n" + TAGS_ADD,
    "uppercase keyword": TAGS_ADD.upper(),
}


@pytest.mark.parametrize("document", BYPASSES.values(), ids=BYPASSES.keys())
@pytest.mark.parametrize("name", ["tags_add", "order_state"])
def test_a_disguised_mutation_never_reaches_the_inner_transport(name: str, document: str) -> None:
    inner = Recording()
    result = ReadOnlyTransport(inner).execute(Request(name, document, {}))
    assert result == NotExecuted(Cause.READ_ONLY, name)
    assert inner.calls == []


def test_the_packaged_query_passes_through_untouched() -> None:
    inner = Recording()
    request = Request("order_state", ORDER_STATE, {"query": "name:#1001"})
    assert ReadOnlyTransport(inner).execute(request) == Ok({})
    assert inner.calls == [request]


def test_the_packaged_mutation_is_refused() -> None:
    inner = Recording()
    request = Request("tags_add", TAGS_ADD, {})
    assert ReadOnlyTransport(inner).execute(request) == NotExecuted(Cause.READ_ONLY, "tags_add")
    assert inner.calls == []


@pytest.mark.parametrize(
    "document",
    [
        ORDER_STATE + "\n",
        ORDER_STATE.replace("shop", "shopp", 1),
        "fragment F on Order { id }\n" + ORDER_STATE,
        "",
    ],
    ids=["trailing newline", "edited body", "prefixed fragment", "empty"],
)
def test_the_right_name_with_an_edited_document_is_refused(document: str) -> None:
    inner = Recording()
    result = ReadOnlyTransport(inner).execute(Request("order_state", document, {}))
    assert result == NotExecuted(Cause.READ_ONLY, "order_state")
    assert inner.calls == []


@pytest.mark.parametrize("name", ["", "missing", "../graphql/order_state", "order_state\x00"])
def test_an_unknown_name_is_refused_even_with_a_packaged_query_text(name: str) -> None:
    inner = Recording()
    result = ReadOnlyTransport(inner).execute(Request(name, ORDER_STATE, {}))
    assert result == NotExecuted(Cause.READ_ONLY, name)
    assert inner.calls == []
