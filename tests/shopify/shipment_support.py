from datetime import UTC, datetime
from pathlib import Path

from fakes.shopify import FakeFulfillment, FakeOrder, FakeTransport

from gisting.shopify.apply_order import ApplyContext
from gisting.shopify.client import AdminClient
from gisting.shopify.ledger import Ledger
from gisting.shopify.plan import EventPlan, Offset, PlanEntry, ShipmentPlan, TrackingPlan

NOW = datetime(2026, 10, 2, 10, 0, tzinfo=UTC)
SECRET = "unit-test-secret"
PLAN_TAG = "shipment-plan-v1"
NOTE_TEMPLATE = (
    "Test order for Gisting Lab experiments in a Shopify development store. Reference {canary}"
)
EVENTS = {
    "IN_TRANSIT": EventPlan("IN_TRANSIT", Offset(-1, 0), Offset(2, 0)),
    "DELIVERED": EventPlan("DELIVERED", Offset(-3, 0), None),
    "OUT_FOR_DELIVERY": EventPlan("OUT_FOR_DELIVERY", Offset(0, -2), Offset(0, 4, same_day=True)),
}


def tracking(number: int) -> TrackingPlan:
    code = f"TP-{number:010d}"
    return TrackingPlan("Test Parcel", code, f"https://tracking.example.com/{code}")


def entry(number: int, scenario: str, quantity: int = 1) -> PlanEntry:
    shipped = {"UNFULFILLED": 0, "PARTIALLY_FULFILLED": quantity - 1}.get(scenario, quantity)
    event_status = "IN_TRANSIT" if scenario == "PARTIALLY_FULFILLED" else scenario
    untracked = scenario in {"UNFULFILLED", "FULFILLED_NO_TRACKING"}
    return PlanEntry(
        order=f"#{number}",
        quantity=quantity,
        scenario=scenario,
        fulfill_quantity=shipped,
        canary=f"GLR-{number:08X}",
        tracking=None if untracked else tracking(number),
        event=None if untracked else EVENTS[event_status],
    )


def make_plan(*entries: PlanEntry) -> ShipmentPlan:
    return ShipmentPlan("shipment-plan-v1", 1, PLAN_TAG, NOTE_TEMPLATE, tuple(entries))


def fulfilled(order: FakeOrder, entry_: PlanEntry, *, events: bool = False) -> FakeFulfillment:
    assert entry_.tracking is not None
    shipment = FakeFulfillment(
        f"gid://shopify/Fulfillment/pre{order.number}",
        entry_.fulfill_quantity,
        [
            {
                "company": entry_.tracking.company,
                "number": entry_.tracking.number,
                "url": entry_.tracking.url,
            }
        ],
    )
    if events:
        shipment.events.append({"id": "gid://shopify/FulfillmentEvent/pre", "status": "IN_TRANSIT"})
    order.remaining -= entry_.fulfill_quantity
    order.fulfillments.append(shipment)
    return shipment


def context(
    tmp_path: Path, transport: FakeTransport, plan: ShipmentPlan, sleeps: list[float] | None = None
) -> ApplyContext:
    record = [] if sleeps is None else sleeps
    client = AdminClient(transport, sleep=record.append)
    return ApplyContext(client, Ledger(tmp_path / "ledger.jsonl"), plan, SECRET, lambda: NOW)
