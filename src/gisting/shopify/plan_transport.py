import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from gisting.shopify.demo_email import demo_email
from gisting.shopify.jsonvalue import Json, JsonObject, MalformedResponse, required_str
from gisting.shopify.plan import (
    Offset,
    PlanEntry,
    PlanFormatError,
    ShipmentPlan,
    format_time,
    load_plan,
    resolve_offset,
)
from gisting.shopify.results import Cause, NotExecuted, Ok, Result
from gisting.shopify.target import BATCH_TAG, DEV_STORE
from gisting.shopify.transport import Request

DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "demo-orders"
LOCAL_SOURCE_FILE = DATA_DIR / "local-source-v1.json"
ORDER_READ = "order_state"
QUERY_PREFIX = "name:"
FULFILLED = "FULFILLED"


class LocalSourceError(ValueError):
    pass


@dataclass(frozen=True)
class LocalSource:
    plan: ShipmentPlan
    seeded_at: datetime


def load_local_source(path: Path = LOCAL_SOURCE_FILE) -> LocalSource:
    try:
        document: Json = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            message = "document must be an object"
            raise MalformedResponse(message)
        plan = load_plan((path.parent / required_str(document, "plan")).read_text(encoding="utf-8"))
        seeded_at = datetime.fromisoformat(required_str(document, "seeded_at"))
    except (OSError, ValueError, PlanFormatError) as error:
        message = f"{path.name}: {type(error).__name__}: {error}"
        raise LocalSourceError(message) from error
    if seeded_at.tzinfo is None:
        message = f"{path.name}: seeded_at needs a time zone"
        raise LocalSourceError(message)
    return LocalSource(plan, seeded_at)


def order_status(entry: PlanEntry) -> str:
    if entry.fulfill_quantity == 0:
        return "UNFULFILLED"
    return FULFILLED if entry.fulfill_quantity >= entry.quantity else "PARTIALLY_FULFILLED"


class PlanTransport:
    def __init__(self, plan: ShipmentPlan, secret: str, seeded_at: datetime) -> None:
        self._plan = plan
        self._secret = secret
        self._seeded_at = seeded_at
        self._entries = {entry.order: entry for entry in plan.entries}

    @property
    def store(self) -> str:
        return DEV_STORE

    def execute(self, request: Request) -> Result:
        if request.name != ORDER_READ:
            return NotExecuted(Cause.READ_ONLY, request.name)
        wanted = str(request.variables.get("query", "")).removeprefix(QUERY_PREFIX)
        entry = self._entries.get(wanted)
        nodes: list[Json] = [] if entry is None else [self._order(entry)]
        shop: JsonObject = {"myshopifyDomain": DEV_STORE, "plan": {"partnerDevelopment": True}}
        return Ok({"shop": shop, "orders": {"nodes": nodes}})

    def _time(self, offset: Offset | None) -> str | None:
        return None if offset is None else format_time(resolve_offset(self._seeded_at, offset))

    def _order(self, entry: PlanEntry) -> JsonObject:
        number = entry.order.removeprefix("#")
        remaining = entry.quantity - entry.fulfill_quantity
        line: JsonObject = {"id": f"gid://shopify/LineItem/{number}", "quantity": entry.quantity}
        fulfillment_line: JsonObject = {
            "id": f"gid://shopify/FulfillmentOrderLineItem/{number}",
            "totalQuantity": entry.quantity,
            "remainingQuantity": remaining,
        }
        fulfillment_order: JsonObject = {
            "id": f"gid://shopify/FulfillmentOrder/{number}",
            "status": "CLOSED" if remaining == 0 else "OPEN",
            "lineItems": {"nodes": [fulfillment_line]},
        }
        fulfillments: list[Json] = (
            [self._fulfillment(entry, number)] if entry.fulfill_quantity else []
        )
        return {
            "id": f"gid://shopify/Order/{number}",
            "name": entry.order,
            "test": True,
            "tags": [BATCH_TAG, self._plan.plan_tag],
            "note": self._plan.note_for(entry),
            "email": demo_email(self._secret, entry.order),
            "displayFulfillmentStatus": order_status(entry),
            "lineItems": {"nodes": [line]},
            "fulfillments": fulfillments,
            "fulfillmentOrders": {"nodes": [fulfillment_order]},
        }

    def _fulfillment(self, entry: PlanEntry, number: str) -> JsonObject:
        tracking: list[Json] = []
        if entry.tracking is not None:
            tracking.append({
                "company": entry.tracking.company,
                "number": entry.tracking.number,
                "url": entry.tracking.url,
            })
        events: list[Json] = []
        status, estimated, delivered = FULFILLED, None, None
        if entry.event is not None:
            happened = self._time(entry.event.happened_at)
            events.append({
                "id": f"gid://shopify/FulfillmentEvent/{number}",
                "status": entry.event.status,
                "happenedAt": happened,
            })
            status, estimated = entry.event.status, self._time(entry.event.estimated_delivery_at)
            delivered = happened if status == "DELIVERED" else None
        return {
            "id": f"gid://shopify/Fulfillment/{number}",
            "status": "SUCCESS",
            "displayStatus": status,
            "estimatedDeliveryAt": estimated,
            "deliveredAt": delivered,
            "totalQuantity": entry.fulfill_quantity,
            "trackingInfo": tracking,
            "events": {"nodes": events},
        }
