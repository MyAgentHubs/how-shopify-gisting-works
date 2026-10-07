import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from gisting.shopify.jsonvalue import Json, JsonObject
from gisting.shopify.order_state import EventState, FulfillmentState, OrderState

CANARY = re.compile(r"GLR-[0-9A-F]{8}")
ORDER_FIELDS = ("order_number", "canary", "fulfillment_status")
SHIPMENT_FIELDS = (
    "transport_status",
    "carrier",
    "tracking_number",
    "estimated_delivery",
    "delivered_at",
    "updated_at",
)
FIELD_NAMES = (*ORDER_FIELDS, *SHIPMENT_FIELDS)


class Source(StrEnum):
    SHOPIFY = "shopify"
    SIMULATED = "simulated"


@dataclass(frozen=True)
class Field:
    value: str | None
    source: Source


@dataclass(frozen=True)
class Shipment:
    fields: Mapping[str, Field]


@dataclass(frozen=True)
class OrderFacts:
    fields: Mapping[str, Field]
    shipments: tuple[Shipment, ...]


def canary_of(note: str | None) -> str | None:
    found = CANARY.search(note or "")
    return found.group() if found else None


def latest_event(events: tuple[EventState, ...]) -> EventState | None:
    dated = [event for event in events if event.happened_at is not None]
    return max(dated, key=lambda event: event.happened_at or "", default=None)


def shipment_values(fulfillment: FulfillmentState) -> dict[str, str | None]:
    latest = latest_event(fulfillment.events)
    tracking = fulfillment.tracking[0] if fulfillment.tracking else None
    return {
        "transport_status": fulfillment.display_status or (latest.status if latest else None),
        "carrier": tracking.company if tracking else None,
        "tracking_number": tracking.number if tracking else None,
        "estimated_delivery": fulfillment.estimated_delivery_at,
        "delivered_at": fulfillment.delivered_at,
        "updated_at": latest.happened_at if latest else None,
    }


def tag(values: Mapping[str, str | None], sources: Mapping[str, Source]) -> dict[str, Field]:
    return {name: Field(value, sources[name]) for name, value in values.items()}


def build_facts(order: OrderState, sources: Mapping[str, Source]) -> OrderFacts:
    values = {
        "order_number": order.name,
        "canary": canary_of(order.note),
        "fulfillment_status": order.status,
    }
    shipments = tuple(
        Shipment(tag(shipment_values(fulfillment), sources)) for fulfillment in order.fulfillments
    )
    return OrderFacts(tag(values, sources), shipments)


def field_json(fields: Mapping[str, Field]) -> JsonObject:
    wire: JsonObject = {}
    for name, field in fields.items():
        wire[name] = {"value": field.value, "source": field.source.value}
    return wire


def facts_json(facts: OrderFacts) -> JsonObject:
    shipments: list[Json] = [field_json(shipment.fields) for shipment in facts.shipments]
    return {**field_json(facts.fields), "shipments": shipments}
