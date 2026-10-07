from dataclasses import replace

from gisting.shopify.apply_order import (
    ApplyContext,
    OrderOutcome,
    OrderRun,
    Status,
    fetch_state,
    report,
)
from gisting.shopify.apply_steps import Job, resolve_times
from gisting.shopify.demo_config import DistributionConfig, StateEvent
from gisting.shopify.order_name import canonical_order_name
from gisting.shopify.order_state import OrderState
from gisting.shopify.plan import EventPlan, Offset, PlanEntry, TrackingPlan
from gisting.shopify.plan_build import tracking_for


class UnknownState(ValueError):
    pass


class UnknownOrder(ValueError):
    pass


def derived_tracking(
    ctx: ApplyContext, config: DistributionConfig, entry: PlanEntry, state: OrderState
) -> TrackingPlan | None:
    if state.fulfillments:
        known = [item for item in state.fulfillments[0].tracking if item.number]
        first = known[0] if known else None
        if first is None or first.number is None:
            return None
        return TrackingPlan(first.company or config.carrier, first.number, first.url or "")
    used = {item.tracking.number for item in ctx.plan.entries if item.tracking}
    return tracking_for(config, ctx.plan.seed, entry.order, used)


def derived_entry(
    ctx: ApplyContext,
    config: DistributionConfig,
    entry: PlanEntry,
    state: OrderState,
    target: StateEvent,
) -> PlanEntry:
    eta = None
    if target.eta_hours is not None:
        eta = Offset.from_hours(target.eta_hours, target.same_day)
    happened = Offset.from_hours(config.set_state_happened_hours)
    shipped = state.fulfillments[0].quantity if state.fulfillments else entry.quantity
    return replace(
        entry,
        scenario=f"SET_{target.status}",
        fulfill_quantity=shipped,
        tracking=derived_tracking(ctx, config, entry, state),
        event=EventPlan(target.status, happened, eta),
    )


def find_entry(ctx: ApplyContext, order: str) -> PlanEntry:
    name = canonical_order_name(order)
    found = next((entry for entry in ctx.plan.entries if entry.order == name), None)
    if found is None:
        raise UnknownOrder(name)
    return found


def set_state(
    ctx: ApplyContext, config: DistributionConfig, order: str, state_name: str
) -> OrderOutcome:
    target = config.set_state_events.get(state_name)
    if target is None:
        raise UnknownState(state_name)
    entry = find_entry(ctx, order)
    state = fetch_state(ctx, entry)
    if isinstance(state, OrderOutcome):
        return state
    if ctx.plan.plan_tag not in state.tags:
        return report(
            ctx, entry, Status.REFUSED, f"订单尚未应用 {ctx.plan.plan_tag}，请先运行 apply"
        )
    derived = derived_entry(ctx, config, entry, state, target)
    job = Job(derived, ctx.plan, resolve_times(derived, ctx.clock()), ctx.email_secret)
    return OrderRun(ctx, job, state, tagging=False).run()
