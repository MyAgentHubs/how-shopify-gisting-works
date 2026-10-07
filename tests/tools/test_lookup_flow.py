import pytest
from fakes.shopify import FakeOrder
from tool_support import (
    POLICY,
    SECRET,
    SESSION,
    canary_for,
    email_for,
    harness,
    obj_at,
    only_shipment,
    public_wire,
    shipped_order,
    state_of,
    tagged,
)

from gisting.shopify.demo_config import load_config
from gisting.shopify.jsonvalue import Json
from gisting.shopify.results import Cause, GraphQLError, NotExecuted, Uncertain
from gisting.shopify.target import BATCH_TAG
from gisting.tools.outcomes import MismatchStage


def test_matching_order_returns_minimal_tagged_facts() -> None:
    response = harness(shipped_order(1042)).lookup("#1042", email_for(1042))
    order = obj_at(response.result, "order")
    assert response.result["status"] == "found"
    assert tagged(order, "order_number") == ("#1042", "shopify")
    assert tagged(order, "canary") == (canary_for(1042), "shopify")
    assert tagged(order, "fulfillment_status") == ("FULFILLED", "shopify")
    shipment = only_shipment(response.result)
    assert tagged(shipment, "transport_status") == ("IN_TRANSIT", "simulated")
    assert tagged(shipment, "carrier") == ("Test Parcel", "shopify")
    assert tagged(shipment, "tracking_number") == ("TP-1042", "shopify")
    assert tagged(shipment, "estimated_delivery") == ("2026-10-05T10:00:00Z", "simulated")
    assert tagged(shipment, "delivered_at") == (None, "simulated")
    assert tagged(shipment, "updated_at") == ("2026-10-01T09:00:00Z", "simulated")


def test_result_carries_no_customer_fields() -> None:
    response = harness(shipped_order(1042)).lookup("#1042", email_for(1042))
    wire = str(response.result).lower()
    assert email_for(1042) not in wire
    assert "@" not in wire
    assert "address" not in wire


def test_order_number_is_accepted_with_or_without_hash_and_leading_zeros() -> None:
    env = harness(shipped_order(1042))
    for raw in ("#1042", "1042", " 1042 ", "01042"):
        assert env.lookup(raw, email_for(1042)).result["status"] == "found"


def test_unfulfilled_order_has_no_shipments() -> None:
    plain = FakeOrder(1050, email=email_for(1050), note="Reference GLR-0000041A")
    plain.tags = [*POLICY.required_tags]
    order = obj_at(harness(plain).lookup("1050", email_for(1050)).result, "order")
    assert order["shipments"] == []
    assert tagged(order, "fulfillment_status") == ("UNFULFILLED", "shopify")
    assert tagged(order, "canary") == ("GLR-0000041A", "shopify")


def test_multiple_shipments_are_listed() -> None:
    order = shipped_order(1060)
    order.fulfillments.append(shipped_order(1061).fulfillments[0])
    result = harness(order).lookup("1060", email_for(1060)).result
    shipments = obj_at(result, "order")["shipments"]
    assert isinstance(shipments, list)
    assert len(shipments) == 2


def test_missing_tracking_and_events_stay_null() -> None:
    order = shipped_order(1070)
    order.fulfillments[0].tracking = []
    order.fulfillments[0].events = []
    order.fulfillments[0].display_status = "FULFILLED"
    shipment = only_shipment(harness(order).lookup("1070", email_for(1070)).result)
    assert tagged(shipment, "carrier")[0] is None
    assert tagged(shipment, "tracking_number")[0] is None
    assert tagged(shipment, "updated_at")[0] is None


def test_second_lookup_is_served_from_cache_after_verification() -> None:
    env = harness(shipped_order(1042))
    env.lookup("1042", email_for(1042))
    calls_after_first = len(env.fake.calls)
    again = env.lookup("1042", email_for(1042))
    assert len(env.fake.calls) == calls_after_first
    assert again.trace.internal.cache_hit is True
    assert again.result["status"] == "found"


def test_cache_hit_still_checks_readback_email() -> None:
    env = harness()
    env.cache.put("#1042", state_of(shipped_order(1042, email="someone@orders.example.com")))
    response = env.lookup("1042", email_for(1042))
    assert response.result["status"] == "no_match"
    assert response.trace.internal.result_type == "Mismatch"
    assert response.trace.internal.detail == MismatchStage.READBACK_EMAIL.value
    assert response.trace.internal.cache_hit is True
    assert env.fake.calls == []


def test_fresh_read_with_other_readback_email_is_a_mismatch() -> None:
    env = harness(shipped_order(1042, email="someone@orders.example.com"))
    response = env.lookup("1042", email_for(1042))
    assert response.trace.internal.result_type == "Mismatch"
    assert response.result["status"] == "no_match"
    assert env.attempts.failures(SESSION) == 1


def test_order_without_email_is_a_mismatch() -> None:
    order = shipped_order(1042)
    order.email = None
    env = harness(order)
    response = env.lookup("1042", email_for(1042))
    assert response.trace.internal.detail == MismatchStage.READBACK_EMAIL.value
    assert env.attempts.failures(SESSION) == 1


@pytest.mark.parametrize(
    "failure",
    [
        Uncertain("timeout"),
        GraphQLError(({"message": "boom"},)),
        NotExecuted(Cause.NETWORK, "down"),
        NotExecuted(Cause.AUTH, "denied"),
    ],
)
def test_upstream_failures_are_unavailable_not_no_match(
    failure: Uncertain | GraphQLError | NotExecuted,
) -> None:
    env = harness(shipped_order(1042))
    for _ in range(3):
        env.fake.fail("order_state", failure)
    response = env.lookup("1042", email_for(1042))
    reference = harness().lookup("1042", email_for(1042))
    assert response.result == {"status": "unavailable"}
    assert response.result != reference.result
    assert response.trace.public.outcome.value == "unavailable"
    assert response.trace.internal.result_type == "UpstreamError"
    assert env.attempts.failures(SESSION) == 0


def test_response_from_another_shop_is_unavailable() -> None:
    env = harness(shipped_order(1042))
    env.fake.shop_domain = "other.myshopify.com"
    response = env.lookup("1042", email_for(1042))
    assert response.trace.internal.detail == Cause.WRONG_STORE.value


def test_missing_order_is_not_found_and_not_cached() -> None:
    env = harness()
    response = env.lookup("1042", email_for(1042))
    assert response.trace.internal.result_type == "NotFound"
    assert env.cache.puts == []
    assert env.attempts.failures(SESSION) == 1


def test_failure_limit_locks_the_session_without_any_io() -> None:
    env = harness(shipped_order(1042))
    for _ in range(POLICY.failure_limit):
        assert env.lookup("1042", "wrong@example.com").result["status"] == "no_match"
    env.cache.gets.clear()
    env.fake.calls.clear()
    locked = env.lookup("1042", email_for(1042))
    assert locked.result == {"status": "locked"}
    assert locked.trace.public.outcome.value == "locked"
    assert locked.trace.internal.result_type == "Locked"
    assert env.cache.gets == []
    assert env.cache.puts == []
    assert env.fake.calls == []
    assert env.lookup("1042", email_for(1042), session_id="other").result["status"] == "found"


def test_matches_and_upstream_errors_do_not_count_as_failures() -> None:
    env = harness(shipped_order(1042))
    for _ in range(POLICY.failure_limit + 2):
        assert env.lookup("1042", email_for(1042)).result["status"] == "found"
    assert env.attempts.failures(SESSION) == 0


@pytest.mark.parametrize("number", ["abc", "", "#", "99999999999999", "1000", "1102", "٣٣٣٣"])
def test_unparseable_and_out_of_range_numbers_never_reach_cache_or_upstream(number: str) -> None:
    env = harness(shipped_order(1042))
    response = env.lookup(number, email_for(1042))
    assert response.result["status"] == "no_match"
    assert env.fake.calls == []
    assert env.cache.gets == []
    assert env.attempts.failures(SESSION) == 1


@pytest.mark.parametrize("number", [1042, [1042], None, {"n": 1042}, True])
def test_non_text_order_number_with_the_right_email_is_a_counted_no_match(number: Json) -> None:
    env = harness(shipped_order(1042))
    response = env.tool.call({"order_number": number, "email": email_for(1042)}, SESSION)
    assert response.result["status"] == "no_match"
    assert response.trace.internal.result_type == "Malformed"
    assert env.attempts.failures(SESSION) == 1
    assert env.fake.calls == []
    assert env.cache.gets == []


@pytest.mark.parametrize("email", [123, [email_for(1042)], None, {"e": 1}, False])
def test_non_text_email_with_the_right_order_number_is_a_counted_no_match(email: Json) -> None:
    env = harness(shipped_order(1042))
    response = env.tool.call({"order_number": "#1042", "email": email}, SESSION)
    assert response.result["status"] == "no_match"
    assert response.trace.internal.result_type == "Mismatch"
    assert env.attempts.failures(SESSION) == 1
    assert env.fake.calls == []
    assert env.cache.gets == []


def test_secret_is_not_in_the_repr_of_deps_or_tool() -> None:
    env = harness(shipped_order(1042))
    for text in (repr(env.deps), repr(env.tool), str(env.tool), repr(env.deps.client)):
        assert SECRET not in text


def non_demo_orders() -> list[FakeOrder]:
    not_test = shipped_order(1042)
    not_test.test = False
    untagged = shipped_order(1042)
    untagged.tags = [BATCH_TAG]
    no_tags = shipped_order(1042)
    no_tags.tags = []
    return [not_test, untagged, no_tags]


@pytest.mark.parametrize("order", non_demo_orders(), ids=["not_test", "no_plan_tag", "no_tags"])
def test_non_demo_orders_are_no_match_even_with_matching_email_and_readback(
    order: FakeOrder,
) -> None:
    env = harness(order)
    response = env.lookup("1042", email_for(1042))
    reference = harness().lookup("1042", email_for(1042))
    assert response.trace.internal.result_type == "NotDemoOrder"
    assert public_wire(response) == public_wire(reference)
    assert env.attempts.failures(SESSION) == 1
    assert canary_for(1042) not in public_wire(response)


def test_cache_hit_also_requires_a_demo_order() -> None:
    order = shipped_order(1042)
    order.tags = []
    env = harness()
    env.cache.put("#1042", state_of(order))
    response = env.lookup("1042", email_for(1042))
    assert response.trace.internal.result_type == "NotDemoOrder"
    assert response.trace.internal.cache_hit is True
    assert env.fake.calls == []


def test_policy_requires_the_plan_tag_of_the_demo_distribution() -> None:
    assert load_config().plan_tag in POLICY.required_tags
