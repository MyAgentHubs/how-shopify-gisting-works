from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from gisting.shopify.client import AdminClient
from gisting.shopify.demo_email import demo_email
from gisting.shopify.order_state import OrderState
from gisting.shopify.plan import PlanEntry, ShipmentPlan, load_plan
from gisting.shopify.plan_transport import (
    LOCAL_SOURCE_FILE,
    PlanTransport,
    load_local_source,
)
from gisting.shopify.results import Cause, NotExecuted
from gisting.shopify.target import BATCH_TAG
from gisting.shopify.transport import Request

ROOT = Path(__file__).resolve().parents[2]
SECRET = "plan-transport-secret-value"
SEEDED = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)
PLAN: ShipmentPlan = load_plan((ROOT / "data/demo-orders/shipment-plan-v1.json").read_text())
CLIENT = AdminClient(PlanTransport(PLAN, SECRET, SEEDED), sleep=lambda _seconds: None)


def entry_of(scenario: str) -> PlanEntry:
    return next(item for item in PLAN.entries if item.scenario == scenario)


def order_of(entry: PlanEntry) -> OrderState:
    state = CLIENT.fetch_order(entry.order)
    assert isinstance(state, OrderState)
    return state


@pytest.mark.parametrize("entry", PLAN.entries, ids=[item.order for item in PLAN.entries])
def test_every_plan_order_reads_back_as_a_tagged_test_order_with_its_own_email(
    entry: PlanEntry,
) -> None:
    state = order_of(entry)
    assert state.test is True
    assert {BATCH_TAG, PLAN.plan_tag} <= set(state.tags)
    assert state.email == demo_email(SECRET, entry.order)
    assert state.note == PLAN.note_for(entry)
    assert state.quantity == entry.quantity


def test_a_shipped_order_carries_its_parcel_event_and_resolved_times() -> None:
    entry = entry_of("IN_TRANSIT")
    assert entry.event is not None
    assert entry.event.estimated_delivery_at is not None
    assert entry.tracking is not None
    (parcel,) = order_of(entry).fulfillments
    offset = entry.event.estimated_delivery_at
    expected = SEEDED + timedelta(days=offset.days, hours=offset.hours)
    assert parcel.estimated_delivery_at == expected.strftime("%Y-%m-%dT%H:%M:%SZ")
    assert parcel.display_status == "IN_TRANSIT"
    assert parcel.tracking[0].number == entry.tracking.number
    assert parcel.tracking[0].company == entry.tracking.company
    assert [event.status for event in parcel.events] == ["IN_TRANSIT"]


def test_fulfillment_status_follows_the_fulfilled_quantity() -> None:
    assert order_of(entry_of("UNFULFILLED")).status == "UNFULFILLED"
    assert order_of(entry_of("UNFULFILLED")).fulfillments == ()
    assert order_of(entry_of("PARTIALLY_FULFILLED")).status == "PARTIALLY_FULFILLED"
    assert order_of(entry_of("DELIVERED")).status == "FULFILLED"


def test_a_delivered_order_has_a_delivery_time_and_no_estimate() -> None:
    (parcel,) = order_of(entry_of("DELIVERED")).fulfillments
    assert parcel.delivered_at is not None
    assert parcel.estimated_delivery_at is None


def test_a_fulfilled_order_without_tracking_has_a_parcel_without_tracking() -> None:
    (parcel,) = order_of(entry_of("FULFILLED_NO_TRACKING")).fulfillments
    assert parcel.tracking == ()
    assert parcel.events == ()


def test_an_order_outside_the_plan_is_not_found() -> None:
    state = CLIENT.fetch_order("#9999")
    assert isinstance(state, NotExecuted)
    assert state.cause is Cause.ORDER_NOT_FOUND


def test_it_refuses_every_request_that_is_not_the_order_read() -> None:
    transport = PlanTransport(PLAN, SECRET, SEEDED)
    result = transport.execute(Request("order_update", "mutation M { x }", {"id": "gid"}))
    assert result == NotExecuted(Cause.READ_ONLY, "order_update")


def test_the_local_source_file_names_the_plan_and_the_seeding_time() -> None:
    source = load_local_source()
    assert source.plan == PLAN
    assert source.seeded_at.tzinfo is not None
    assert LOCAL_SOURCE_FILE.is_file()
