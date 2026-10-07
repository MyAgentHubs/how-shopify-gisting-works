import json
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta

from gisting.shopify.jsonvalue import (
    Json,
    JsonObject,
    MalformedResponse,
    object_items,
    optional_object,
    optional_str,
    required_bool,
    required_int,
    required_list,
    required_object,
    required_str,
)

HOURS_PER_DAY = 24
END_OF_DAY = time(23, 59, tzinfo=UTC)
TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
JSON_INDENT = 2


class PlanFormatError(ValueError):
    pass


@dataclass(frozen=True)
class Offset:
    days: int
    hours: int
    same_day: bool = False

    @classmethod
    def from_hours(cls, total: int, same_day: bool = False) -> "Offset":
        days, hours = divmod(abs(total), HOURS_PER_DAY)
        sign = -1 if total < 0 else 1
        return cls(sign * days, sign * hours, same_day)


@dataclass(frozen=True)
class TrackingPlan:
    company: str
    number: str
    url: str


@dataclass(frozen=True)
class EventPlan:
    status: str
    happened_at: Offset
    estimated_delivery_at: Offset | None


@dataclass(frozen=True)
class PlanEntry:
    order: str
    quantity: int
    scenario: str
    fulfill_quantity: int
    canary: str
    tracking: TrackingPlan | None
    event: EventPlan | None


@dataclass(frozen=True)
class ShipmentPlan:
    version: str
    seed: int
    plan_tag: str
    note_template: str
    entries: tuple[PlanEntry, ...]

    def note_for(self, entry: PlanEntry) -> str:
        return self.note_template.format(canary=entry.canary)


def resolve_offset(now: datetime, offset: Offset) -> datetime:
    moment = now + timedelta(days=offset.days, hours=offset.hours)
    if not offset.same_day:
        return moment
    return min(moment, datetime.combine(now.date(), END_OF_DAY))


def format_time(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime(TIME_FORMAT)


def offset_json(offset: Offset | None) -> JsonObject | None:
    if offset is None:
        return None
    return {"days": offset.days, "hours": offset.hours, "same_day": offset.same_day}


def entry_json(entry: PlanEntry) -> JsonObject:
    tracking: JsonObject | None = None
    if entry.tracking is not None:
        tracking = {
            "company": entry.tracking.company,
            "number": entry.tracking.number,
            "url": entry.tracking.url,
        }
    event: JsonObject | None = None
    if entry.event is not None:
        event = {
            "status": entry.event.status,
            "happened_at": offset_json(entry.event.happened_at),
            "estimated_delivery_at": offset_json(entry.event.estimated_delivery_at),
        }
    return {
        "order": entry.order,
        "quantity": entry.quantity,
        "scenario": entry.scenario,
        "fulfill_quantity": entry.fulfill_quantity,
        "canary": entry.canary,
        "tracking": tracking,
        "event": event,
    }


def dump_plan(plan: ShipmentPlan) -> str:
    document: JsonObject = {
        "version": plan.version,
        "seed": plan.seed,
        "plan_tag": plan.plan_tag,
        "note_template": plan.note_template,
        "entries": [entry_json(entry) for entry in plan.entries],
    }
    return json.dumps(document, indent=JSON_INDENT, sort_keys=True, ensure_ascii=False) + "\n"


def parse_offset(node: JsonObject | None) -> Offset | None:
    if node is None:
        return None
    return Offset(
        required_int(node, "days"), required_int(node, "hours"), required_bool(node, "same_day")
    )


def parse_event(node: JsonObject | None) -> EventPlan | None:
    if node is None:
        return None
    happened = parse_offset(required_object(node, "happened_at"))
    if happened is None:
        raise MalformedResponse("happened_at")
    eta = parse_offset(optional_object(node, "estimated_delivery_at"))
    return EventPlan(required_str(node, "status"), happened, eta)


def parse_tracking(node: JsonObject | None) -> TrackingPlan | None:
    if node is None:
        return None
    company = optional_str(node, "company")
    return TrackingPlan(company or "", required_str(node, "number"), required_str(node, "url"))


def parse_entry(node: JsonObject) -> PlanEntry:
    return PlanEntry(
        order=required_str(node, "order"),
        quantity=required_int(node, "quantity"),
        scenario=required_str(node, "scenario"),
        fulfill_quantity=required_int(node, "fulfill_quantity"),
        canary=required_str(node, "canary"),
        tracking=parse_tracking(optional_object(node, "tracking")),
        event=parse_event(optional_object(node, "event")),
    )


def load_plan(text: str) -> ShipmentPlan:
    try:
        document: Json = json.loads(text)
        if not isinstance(document, dict):
            raise MalformedResponse("plan")
        return ShipmentPlan(
            version=required_str(document, "version"),
            seed=required_int(document, "seed"),
            plan_tag=required_str(document, "plan_tag"),
            note_template=required_str(document, "note_template"),
            entries=tuple(
                parse_entry(node)
                for node in object_items(required_list(document, "entries"), "entries")
            ),
        )
    except ValueError as error:
        raise PlanFormatError(str(error)) from error
