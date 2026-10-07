import json
from dataclasses import dataclass
from typing import cast

from gisting.eval.dates import DateRef
from gisting.prompt.parcel_render import parsed_day
from gisting.prompt.replies import UNSHIPPED

ORDER_KEY = "order"
SHIPMENTS_KEY = "shipments"
VALUE_KEY = "value"


@dataclass(frozen=True)
class ParcelFacts:
    status: str | None
    carrier: str | None
    tracking: str | None
    estimated: tuple[DateRef, ...]
    delivered: tuple[DateRef, ...]


@dataclass(frozen=True)
class FoundFacts:
    fulfillment: str | None
    parcels: tuple[ParcelFacts, ...]
    others: tuple[DateRef, ...]

    @property
    def shipments(self) -> int:
        return len(self.parcels)

    @property
    def transports(self) -> tuple[str, ...]:
        return tuple(parcel.status for parcel in self.parcels if parcel.status)

    @property
    def carriers(self) -> tuple[str, ...]:
        return tuple(parcel.carrier for parcel in self.parcels if parcel.carrier)

    @property
    def trackings(self) -> tuple[str, ...]:
        return tuple(parcel.tracking for parcel in self.parcels if parcel.tracking)

    @property
    def estimated(self) -> tuple[DateRef, ...]:
        return tuple(day for parcel in self.parcels for day in parcel.estimated)

    @property
    def delivered(self) -> tuple[DateRef, ...]:
        return tuple(day for parcel in self.parcels for day in parcel.delivered)

    @property
    def days(self) -> tuple[DateRef, ...]:
        return (*self.estimated, *self.delivered, *self.others)


def objects(value: object) -> list[dict[str, object]]:
    items = cast(list[object], value) if isinstance(value, list) else []
    return [cast(dict[str, object], item) for item in items if isinstance(item, dict)]


def value_of(node: dict[str, object], key: str) -> str | None:
    field = node.get(key)
    inner = cast(dict[str, object], field).get(VALUE_KEY) if isinstance(field, dict) else field
    return inner if isinstance(inner, str) and inner.strip() else None


def days_of(stamp: str | None) -> tuple[DateRef, ...]:
    day = parsed_day(stamp)
    return (DateRef(day.year, day.month, day.day),) if day else ()


def parcel_of(node: dict[str, object]) -> ParcelFacts:
    return ParcelFacts(
        status=value_of(node, "transport_status"),
        carrier=value_of(node, "carrier"),
        tracking=value_of(node, "tracking_number"),
        estimated=days_of(value_of(node, "estimated_delivery")),
        delivered=days_of(value_of(node, "delivered_at")),
    )


def parse_found(content: str) -> FoundFacts | None:
    try:
        document: object = json.loads(content)
    except (ValueError, RecursionError):
        return None
    root = cast(dict[str, object], document) if isinstance(document, dict) else {}
    order = root.get(ORDER_KEY)
    if root.get("status") != "found" or not isinstance(order, dict):
        return None
    fields = cast(dict[str, object], order)
    fulfillment = value_of(fields, "fulfillment_status")
    shipments = [] if fulfillment == UNSHIPPED else objects(fields.get(SHIPMENTS_KEY))
    return FoundFacts(
        fulfillment=fulfillment,
        parcels=tuple(parcel_of(node) for node in shipments),
        others=tuple(day for node in shipments for day in days_of(value_of(node, "updated_at"))),
    )
