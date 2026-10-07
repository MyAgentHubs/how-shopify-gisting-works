import hashlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from gisting.shopify.demo_config import DistributionConfig, ScenarioSpec
from gisting.shopify.order_name import canonical_order_name
from gisting.shopify.plan import (
    EventPlan,
    Offset,
    PlanEntry,
    ShipmentPlan,
    TrackingPlan,
)

TRACKING_DIGITS = 10
CANARY_HEX_CHARS = 8


class PlanBuildError(ValueError):
    pass


class OrderCountMismatch(PlanBuildError):
    pass


class NotEnoughOrders(PlanBuildError):
    pass


@dataclass(frozen=True)
class OrderRef:
    name: str
    quantity: int


def digest(seed: int, purpose: str, name: str, salt: int = 0) -> int:
    material = f"{seed}:{purpose}:{name}:{salt}".encode()
    return int(hashlib.sha256(material).hexdigest(), 16)


def draw(seed: int, purpose: str, name: str, bounds: tuple[int, int]) -> int:
    low, high = bounds
    return low + digest(seed, purpose, name) % (high - low + 1)


def unique_token(
    seed: int, purpose: str, name: str, render: Callable[[int], str], used: set[str]
) -> str:
    salt = 0
    while (token := render(digest(seed, purpose, name, salt))) in used:
        salt += 1
    used.add(token)
    return token


def tracking_number(config: DistributionConfig, raw: int) -> str:
    return f"{config.tracking_prefix}{raw % 10**TRACKING_DIGITS:0{TRACKING_DIGITS}d}"


def tracking_for(config: DistributionConfig, seed: int, order: str, used: set[str]) -> TrackingPlan:
    number = unique_token(seed, "tracking", order, lambda raw: tracking_number(config, raw), used)
    return TrackingPlan(config.carrier, number, f"{config.tracking_url_base}{number}")


def canary_for(config: DistributionConfig, seed: int, order: str, used: set[str]) -> str:
    def render(raw: int) -> str:
        return f"{config.canary_prefix}{raw:X}"[: len(config.canary_prefix) + CANARY_HEX_CHARS]

    return unique_token(seed, "canary", order, render, used)


def assign(
    orders: Sequence[OrderRef], config: DistributionConfig, seed: int
) -> dict[str, list[OrderRef]]:
    expected = sum(spec.count for spec in config.scenarios)
    if len(orders) != expected:
        raise OrderCountMismatch(expected, len(orders))
    ranked = sorted(orders, key=lambda order: digest(seed, "rank", order.name))
    assigned: dict[str, list[OrderRef]] = {}
    constrained = sorted(config.scenarios, key=lambda spec: -spec.min_quantity)
    for spec in constrained:
        eligible = [order for order in ranked if order.quantity >= spec.min_quantity]
        if len(eligible) < spec.count:
            raise NotEnoughOrders(spec.name)
        assigned[spec.name] = eligible[: spec.count]
        taken = {order.name for order in assigned[spec.name]}
        ranked = [order for order in ranked if order.name not in taken]
    return assigned


def fulfilled_quantity(spec: ScenarioSpec, quantity: int) -> int:
    return {"none": 0, "all": quantity, "all_but_one": quantity - 1}[spec.fulfill]


def event_for(spec: ScenarioSpec, seed: int, order: OrderRef, index: int) -> EventPlan | None:
    if spec.event is None or spec.happened_hours is None:
        return None
    happened = Offset.from_hours(draw(seed, "happened", order.name, spec.happened_hours))
    eta: Offset | None = None
    if spec.eta_hours:
        bounds = spec.eta_hours[index % len(spec.eta_hours)]
        eta = Offset.from_hours(draw(seed, "eta", order.name, bounds), spec.eta_same_day)
    return EventPlan(spec.event, happened, eta)


def build_plan(
    orders: Sequence[OrderRef], config: DistributionConfig, seed: int | None = None
) -> ShipmentPlan:
    chosen = config.seed if seed is None else seed
    assigned = assign(orders, config, chosen)
    used_tracking: set[str] = set()
    used_canary: set[str] = set()
    entries: list[PlanEntry] = []
    for spec in config.scenarios:
        for index, order in enumerate(assigned[spec.name]):
            name = canonical_order_name(order.name)
            tracking = tracking_for(config, chosen, name, used_tracking) if spec.tracking else None
            entries.append(
                PlanEntry(
                    order=name,
                    quantity=order.quantity,
                    scenario=spec.name,
                    fulfill_quantity=fulfilled_quantity(spec, order.quantity),
                    canary=canary_for(config, chosen, name, used_canary),
                    tracking=tracking,
                    event=event_for(spec, chosen, order, index),
                )
            )
    entries.sort(key=lambda entry: int(entry.order[1:]))
    return ShipmentPlan(
        config.version, chosen, config.plan_tag, config.note_template, tuple(entries)
    )
