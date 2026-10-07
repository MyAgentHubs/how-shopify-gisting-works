import pytest
from fakes.shopify import FakeOrder, FakeTransport

from gisting.shopify.client import AdminClient, Verified
from gisting.shopify.jsonvalue import JsonObject
from gisting.shopify.order_name import InvalidOrderName, canonical_order_name
from gisting.shopify.order_state import OrderState
from gisting.shopify.results import Cause, GraphQLError, NotExecuted, Ok, Uncertain
from gisting.shopify.target import BATCH_TAG, StoreNotAllowed


def make(*orders: FakeOrder) -> tuple[AdminClient, FakeTransport, list[float]]:
    sleeps: list[float] = []
    fake = FakeTransport(list(orders))
    return AdminClient(fake, sleep=sleeps.append), fake, sleeps


def fetch(client: AdminClient, name: str) -> OrderState:
    order = client.fetch_order(name)
    assert isinstance(order, OrderState)
    return order


def verified(client: AdminClient, name: str) -> Verified:
    granted = client.writable(fetch(client, name))
    assert isinstance(granted, Verified)
    return granted


def update_variables(order: FakeOrder) -> JsonObject:
    return {"input": {"id": order.gid, "note": "n"}}


def test_non_dev_store_transport_is_rejected() -> None:
    with pytest.raises(StoreNotAllowed):
        AdminClient(FakeTransport([], store="other.myshopify.com"))


def test_response_from_other_shop_is_not_executed() -> None:
    fake = FakeTransport([FakeOrder(1002)], shop_domain="other.myshopify.com")
    result = AdminClient(fake).fetch_order("1002")
    assert result == NotExecuted(Cause.WRONG_STORE, "#1002")


def test_order_name_is_canonicalised() -> None:
    assert canonical_order_name(" 1002 ") == "#1002"
    with pytest.raises(InvalidOrderName):
        canonical_order_name("1002; drop")


def test_fetch_finds_order_by_name() -> None:
    client, _, _ = make(FakeOrder(1002, quantity=3))
    state = fetch(client, "#1002")
    assert (state.name, state.quantity, state.status) == ("#1002", 3, "UNFULFILLED")


def test_missing_order_is_not_executed() -> None:
    client, _, _ = make()
    assert client.fetch_order("1002") == NotExecuted(Cause.ORDER_NOT_FOUND, "#1002")


def test_read_retries_uncertain_then_succeeds() -> None:
    client, fake, sleeps = make(FakeOrder(1002))
    fake.fail("order_state", Uncertain("tls"))
    fake.fail("order_state", Uncertain("tls"))
    assert isinstance(client.fetch_order("1002"), OrderState)
    assert len(fake.calls) == 3
    assert len(sleeps) == 2


def test_read_gives_up_after_attempts() -> None:
    client, fake, _ = make(FakeOrder(1002))
    for _ in range(3):
        fake.fail("order_state", Uncertain("tls"))
    assert isinstance(client.fetch_order("1002"), Uncertain)
    assert len(fake.calls) == 3


def test_non_test_order_is_not_writable() -> None:
    client, _, _ = make(FakeOrder(1002, test=False))
    result = client.writable(fetch(client, "1002"))
    assert result == NotExecuted(Cause.NOT_TEST_ORDER, "#1002")


def test_order_without_batch_tag_is_not_writable() -> None:
    client, _, _ = make(FakeOrder(1002, tags=["other"]))
    result = client.writable(fetch(client, "1002"))
    assert result == NotExecuted(Cause.MISSING_BATCH_TAG, "#1002")


def test_forged_verification_cannot_write_non_test_order() -> None:
    order = FakeOrder(1002, test=False)
    client, fake, _ = make(order)
    forged = Verified(order.gid, order.name)
    result = client.write(forged, "order_update", update_variables(order))
    assert result == NotExecuted(Cause.UNVERIFIED_ORDER, "#1002")
    assert fake.writes == []


def test_write_to_verified_order_goes_through() -> None:
    order = FakeOrder(1002)
    client, fake, _ = make(order)
    result = client.write(verified(client, "1002"), "order_update", update_variables(order))
    assert isinstance(result, Ok)
    assert order.note == "n"
    assert len(fake.writes) == 1


def test_write_naming_foreign_id_is_refused() -> None:
    mine, other = FakeOrder(1002), FakeOrder(1003)
    client, fake, _ = make(mine, other)
    result = client.write(verified(client, "1002"), "order_update", update_variables(other))
    assert result == NotExecuted(Cause.FOREIGN_ID, other.gid)
    assert fake.writes == []


def test_write_without_any_id_is_refused() -> None:
    client, fake, _ = make(FakeOrder(1002))
    result = client.write(verified(client, "1002"), "tags_add", {"tags": ["x"]})
    assert isinstance(result, NotExecuted)
    assert fake.writes == []


def test_query_document_is_refused_as_write() -> None:
    order = FakeOrder(1002)
    client, _, _ = make(order)
    result = client.write(verified(client, "1002"), "order_state", {"id": order.gid})
    assert result == NotExecuted(Cause.WRONG_DOCUMENT_KIND, "order_state")


def test_unknown_document_is_refused() -> None:
    order = FakeOrder(1002)
    client, _, _ = make(order)
    result = client.write(verified(client, "1002"), "order_delete", {"id": order.gid})
    assert result == NotExecuted(Cause.UNKNOWN_DOCUMENT, "order_delete")


def test_user_errors_become_graphql_error() -> None:
    order = FakeOrder(1002)
    client, fake, _ = make(order)
    fake.fail("tags_add", Ok({"tagsAdd": {"userErrors": [{"message": "bad"}]}}))
    result = client.write(verified(client, "1002"), "tags_add", {"id": order.gid, "tags": ["x"]})
    assert result == GraphQLError(({"message": "bad"},), user_errors=True)


def test_uncertain_write_is_returned_and_never_retried() -> None:
    order = FakeOrder(1002)
    client, fake, sleeps = make(order)
    fake.fail("order_update", Uncertain("tls"), applied=True)
    result = client.write(verified(client, "1002"), "order_update", update_variables(order))
    assert result == Uncertain("tls")
    assert len(fake.writes) == 1
    assert sleeps == []


def test_batch_tag_constant_matches_seed_batch() -> None:
    assert BATCH_TAG == "gisting-batch-20260930-v1"
