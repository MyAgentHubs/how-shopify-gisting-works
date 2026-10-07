from dataclasses import dataclass, replace
from datetime import datetime

from gisting.shopify.assess import OPEN_STATUSES, Step
from gisting.shopify.demo_email import demo_email
from gisting.shopify.jsonvalue import Json, JsonObject, required_object, required_str
from gisting.shopify.order_state import EventState, FulfillmentState, OrderState, Tracking
from gisting.shopify.plan import PlanEntry, ShipmentPlan, format_time, resolve_offset


@dataclass(frozen=True)
class Times:
    happened_at: str | None
    estimated_delivery_at: str | None


@dataclass(frozen=True)
class Job:
    entry: PlanEntry
    plan: ShipmentPlan
    times: Times
    secret: str

    @property
    def email(self) -> str:
        return demo_email(self.secret, self.entry.order)


def resolve_times(entry: PlanEntry, now: datetime) -> Times:
    if entry.event is None:
        return Times(None, None)
    eta = entry.event.estimated_delivery_at
    return Times(
        format_time(resolve_offset(now, entry.event.happened_at)),
        format_time(resolve_offset(now, eta)) if eta is not None else None,
    )


def fulfillment_groups(state: OrderState, entry: PlanEntry) -> list[Json]:
    need = entry.fulfill_quantity
    groups: list[Json] = []
    for fulfillment_order in state.fulfillment_orders:
        lines: list[Json] = []
        for line in fulfillment_order.lines if fulfillment_order.status in OPEN_STATUSES else ():
            take = min(need, line.remaining)
            if take > 0:
                lines.append({"id": line.id, "quantity": take})
                need -= take
        if lines:
            groups.append({
                "fulfillmentOrderId": fulfillment_order.id,
                "fulfillmentOrderLineItems": lines,
            })
    return groups


def fulfillment_variables(state: OrderState, entry: PlanEntry) -> JsonObject:
    fulfillment: JsonObject = {
        "notifyCustomer": False,
        "lineItemsByFulfillmentOrder": fulfillment_groups(state, entry),
    }
    if entry.tracking is not None:
        fulfillment["trackingInfo"] = {
            "company": entry.tracking.company,
            "number": entry.tracking.number,
            "url": entry.tracking.url,
        }
    return {"fulfillment": fulfillment}


def event_variables(state: OrderState, job: Job) -> JsonObject:
    assert job.entry.event is not None
    event: JsonObject = {
        "fulfillmentId": state.fulfillments[0].id,
        "status": job.entry.event.status,
        "happenedAt": job.times.happened_at,
    }
    if job.times.estimated_delivery_at is not None:
        event["estimatedDeliveryAt"] = job.times.estimated_delivery_at
    return {"fulfillmentEvent": event}


def step_variables(step: Step, state: OrderState, job: Job) -> JsonObject:
    if step is Step.UPDATE_ORDER:
        fields: JsonObject = {
            "id": state.id,
            "email": job.email,
            "note": job.plan.note_for(job.entry),
        }
        return {"input": fields}
    if step is Step.CREATE_FULFILLMENT:
        return fulfillment_variables(state, job.entry)
    if step is Step.CREATE_EVENT:
        return event_variables(state, job)
    return {"id": state.id, "tags": [job.plan.plan_tag]}


def created_fulfillment(state: OrderState, entry: PlanEntry, data: JsonObject) -> OrderState:
    payload = required_object(required_object(data, "fulfillmentCreate"), "fulfillment")
    identifier = required_str(payload, "id")
    tracking = (
        (Tracking(entry.tracking.company, entry.tracking.number, entry.tracking.url),)
        if entry.tracking
        else ()
    )
    created = FulfillmentState(
        identifier, "SUCCESS", None, entry.fulfill_quantity, None, None, tracking, ()
    )
    return replace(state, fulfillments=(*state.fulfillments, created))


def created_event(state: OrderState, job: Job) -> OrderState:
    assert job.entry.event is not None
    first, *rest = state.fulfillments
    event = EventState(job.entry.event.status, job.times.happened_at)
    return replace(state, fulfillments=(replace(first, events=(*first.events, event)), *rest))


def advance_state(step: Step, state: OrderState, job: Job, data: JsonObject) -> OrderState:
    if step is Step.UPDATE_ORDER:
        return replace(state, note=job.plan.note_for(job.entry))
    if step is Step.CREATE_FULFILLMENT:
        return created_fulfillment(state, job.entry, data)
    if step is Step.CREATE_EVENT:
        return created_event(state, job)
    return replace(state, tags=(*state.tags, job.plan.plan_tag))
