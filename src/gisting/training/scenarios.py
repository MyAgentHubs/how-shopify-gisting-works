import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from gisting.shopify.jsonvalue import (
    JsonObject,
    object_items,
    optional_object,
    required_int,
    required_list,
    required_str,
)
from gisting.tools.facts import OrderFacts, Shipment, tag
from gisting.tools.policy import LookupPolicy
from gisting.training.files import PLAN_FILE, read_object

TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
PARTIAL = "PARTIALLY_FULFILLED"
UNFULFILLED = "UNFULFILLED"
FULFILLED = "FULFILLED"
HOURS_PER_DAY = 24


@dataclass(frozen=True)
class Offset:
    days: int
    hours: int


@dataclass(frozen=True)
class OrderEntry:
    number: str
    scenario: str
    canary: str
    carrier: str | None
    tracking_number: str | None
    status: str | None
    happened_at: Offset | None
    estimated_delivery_at: Offset | None


def parse_offset(parent: JsonObject, key: str) -> Offset | None:
    node = optional_object(parent, key)
    if node is None:
        return None
    return Offset(required_int(node, "days"), required_int(node, "hours"))


def parse_entry(node: JsonObject) -> OrderEntry:
    event = optional_object(node, "event")
    tracking = optional_object(node, "tracking")
    return OrderEntry(
        number=required_str(node, "order"),
        scenario=required_str(node, "scenario"),
        canary=required_str(node, "canary"),
        carrier=required_str(tracking, "company") if tracking else None,
        tracking_number=required_str(tracking, "number") if tracking else None,
        status=required_str(event, "status") if event else None,
        happened_at=parse_offset(event, "happened_at") if event else None,
        estimated_delivery_at=parse_offset(event, "estimated_delivery_at") if event else None,
    )


def load_entries(path: Path = PLAN_FILE) -> list[OrderEntry]:
    document = read_object(path)
    return [
        parse_entry(node) for node in object_items(required_list(document, "entries"), "entries")
    ]


def split_orders(
    entries: list[OrderEntry], dev_fraction: float, seed: int
) -> dict[str, list[OrderEntry]]:
    pools: dict[str, list[OrderEntry]] = {"train": [], "dev": []}
    for scenario in sorted({entry.scenario for entry in entries}):
        group = sorted((e for e in entries if e.scenario == scenario), key=lambda e: e.number)
        random.Random(f"{seed}:{scenario}").shuffle(group)
        dev_count = max(1, round(len(group) * dev_fraction))
        pools["dev"].extend(group[:dev_count])
        pools["train"].extend(group[dev_count:])
    return pools


def stamp(anchor: datetime, offset: Offset | None) -> str | None:
    if offset is None:
        return None
    return (anchor + timedelta(days=offset.days, hours=offset.hours)).strftime(TIME_FORMAT)


def fulfillment_status(entry: OrderEntry) -> str:
    return entry.scenario if entry.scenario in (PARTIAL, UNFULFILLED) else FULFILLED


def shipment_fields(entry: OrderEntry, anchor: datetime) -> dict[str, str | None]:
    delivered = entry.scenario == "DELIVERED"
    return {
        "transport_status": entry.status or FULFILLED,
        "carrier": entry.carrier,
        "tracking_number": entry.tracking_number,
        "estimated_delivery": stamp(anchor, entry.estimated_delivery_at),
        "delivered_at": stamp(anchor, entry.happened_at) if delivered else None,
        "updated_at": stamp(anchor, entry.happened_at),
    }


def build_facts(entry: OrderEntry, anchor: datetime, policy: LookupPolicy) -> OrderFacts:
    order_fields = {
        "order_number": entry.number,
        "canary": entry.canary,
        "fulfillment_status": fulfillment_status(entry),
    }
    shipments: tuple[Shipment, ...] = ()
    if entry.scenario != UNFULFILLED:
        shipments = (Shipment(tag(shipment_fields(entry, anchor), policy.sources)),)
    return OrderFacts(tag(order_fields, policy.sources), shipments)
