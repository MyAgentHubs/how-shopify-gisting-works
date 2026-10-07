from dataclasses import dataclass
from enum import StrEnum

from gisting.shopify.order_state import FulfillmentState, OrderState
from gisting.shopify.plan import PlanEntry, ShipmentPlan

OPEN_STATUSES = frozenset({"OPEN", "IN_PROGRESS"})


class Step(StrEnum):
    UPDATE_ORDER = "order_update"
    CREATE_FULFILLMENT = "fulfillment_create"
    CREATE_EVENT = "fulfillment_event_create"
    ADD_TAG = "tags_add"


@dataclass(frozen=True)
class Assessment:
    skip: bool = False
    diverged: str | None = None
    steps: tuple[Step, ...] = ()


def has_event(fulfillment: FulfillmentState, status: str) -> bool:
    return any(event.status == status for event in fulfillment.events)


def expected_status(entry: PlanEntry) -> str:
    if entry.fulfill_quantity == 0:
        return "UNFULFILLED"
    return "FULFILLED" if entry.fulfill_quantity >= entry.quantity else "PARTIALLY_FULFILLED"


def email_status(state: OrderState, expected: str) -> str:
    if state.email is None:
        return "missing"
    return "matches" if state.email == expected else "mismatch"


def open_quantity(state: OrderState) -> int:
    return sum(
        line.remaining
        for fulfillment_order in state.fulfillment_orders
        if fulfillment_order.status in OPEN_STATUSES
        for line in fulfillment_order.lines
    )


def fulfillment_divergence(fulfillment: FulfillmentState, entry: PlanEntry) -> str | None:
    if fulfillment.quantity != entry.fulfill_quantity:
        return f"已发货数量 {fulfillment.quantity} 与计划 {entry.fulfill_quantity} 不符"
    numbers = tuple(item.number for item in fulfillment.tracking if item.number)
    planned: tuple[str, ...] = (entry.tracking.number,) if entry.tracking else ()
    if numbers != planned:
        return "运单信息与计划不符"
    return None


def unshipped_divergence(state: OrderState, entry: PlanEntry) -> str | None:
    if state.status != "UNFULFILLED":
        return f"订单状态 {state.status} 无法按计划处理"
    if open_quantity(state) < entry.fulfill_quantity:
        return f"可发货数量 {open_quantity(state)} 少于计划 {entry.fulfill_quantity}"
    return None


def shipped_divergence(
    first: FulfillmentState, others: list[FulfillmentState], entry: PlanEntry
) -> str | None:
    if entry.fulfill_quantity == 0:
        return "已发货的订单无法再按计划改为未发货"
    if others:
        return f"已有 {len(others) + 1} 条发货记录，计划只允许 1 条"
    return fulfillment_divergence(first, entry)


def divergence(state: OrderState, entry: PlanEntry) -> str | None:
    if state.quantity != entry.quantity:
        return f"订单数量 {state.quantity} 与计划 {entry.quantity} 不符"
    if not state.fulfillments:
        return unshipped_divergence(state, entry)
    first, *others = state.fulfillments
    return shipped_divergence(first, others, entry)


def pending_steps(
    state: OrderState, entry: PlanEntry, plan: ShipmentPlan, email: str
) -> list[Step]:
    steps: list[Step] = []
    fulfillment = state.fulfillments[0] if state.fulfillments else None
    if state.note != plan.note_for(entry) or email_status(state, email) != "matches":
        steps.append(Step.UPDATE_ORDER)
    if entry.fulfill_quantity and fulfillment is None:
        steps.append(Step.CREATE_FULFILLMENT)
    event = entry.event
    if event is not None and (fulfillment is None or not has_event(fulfillment, event.status)):
        steps.append(Step.CREATE_EVENT)
    return steps


def assess(
    state: OrderState, entry: PlanEntry, plan: ShipmentPlan, email: str, *, tagging: bool = True
) -> Assessment:
    if tagging and plan.plan_tag in state.tags:
        return Assessment(skip=True)
    problem = divergence(state, entry)
    if problem is not None:
        return Assessment(diverged=problem)
    steps = pending_steps(state, entry, plan, email)
    if tagging:
        steps.append(Step.ADD_TAG)
    return Assessment(steps=tuple(steps))


def check_outcome(
    state: OrderState, entry: PlanEntry, plan: ShipmentPlan, email: str
) -> str | None:
    assessment = assess(state, entry, plan, email, tagging=False)
    if assessment.diverged is not None:
        return assessment.diverged
    status = email_status(state, email)
    if status != "matches":
        return f"email 回读 {status}"
    if assessment.steps:
        return "仍有未完成步骤: " + ",".join(step.value for step in assessment.steps)
    if state.status != expected_status(entry):
        return f"订单状态 {state.status}，期望 {expected_status(entry)}"
    return None
