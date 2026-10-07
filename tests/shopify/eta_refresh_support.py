from fakes.shopify import FakeOrder, FakeTransport
from shipment_support import PLAN_TAG, entry, fulfilled

from gisting.shopify.plan import PlanEntry

OLD_ETA = "2026-10-01T10:00:00Z"
NEW_ETA = "2026-10-04T10:00:00Z"


def seeded(number: int = 1006, scenario: str = "IN_TRANSIT") -> tuple[PlanEntry, FakeOrder]:
    planned = entry(number, scenario)
    order = FakeOrder(number)
    order.tags.append(PLAN_TAG)
    shipment = fulfilled(order, planned)
    assert planned.event is not None
    shipment.events.append({
        "status": planned.event.status,
        "happenedAt": "2026-10-01T09:00:00Z",
    })
    shipment.estimated_delivery_at = OLD_ETA if planned.event.estimated_delivery_at else None
    return planned, order


def read_calls(fake: FakeTransport) -> int:
    return sum(call.name == "order_state" for call in fake.calls)
