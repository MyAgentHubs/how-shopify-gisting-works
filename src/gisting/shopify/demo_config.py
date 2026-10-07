import json
from dataclasses import dataclass
from importlib import resources

from gisting.shopify.jsonvalue import (
    Json,
    JsonObject,
    MalformedResponse,
    as_pair,
    object_items,
    optional_object,
    optional_str,
    required_bool,
    required_int,
    required_list,
    required_object,
    required_pair,
    required_str,
)

CONFIG_FILE = "demo_distribution.json"
FULFILL_MODES = frozenset({"none", "all", "all_but_one"})


@dataclass(frozen=True)
class ScenarioSpec:
    name: str
    count: int
    fulfill: str
    tracking: bool
    event: str | None
    min_quantity: int
    happened_hours: tuple[int, int] | None
    eta_hours: tuple[tuple[int, int], ...]
    eta_same_day: bool


@dataclass(frozen=True)
class StateEvent:
    status: str
    eta_hours: int | None
    same_day: bool


@dataclass(frozen=True)
class DistributionConfig:
    version: str
    seed: int
    plan_tag: str
    carrier: str
    tracking_prefix: str
    tracking_url_base: str
    canary_prefix: str
    note_template: str
    scenarios: tuple[ScenarioSpec, ...]
    set_state_happened_hours: int
    set_state_events: dict[str, StateEvent]
    stale_grace_minutes: int
    eta_days_min: int
    eta_days_max: int


def parse_scenario(node: JsonObject) -> ScenarioSpec:
    fulfill = required_str(node, "fulfill")
    if fulfill not in FULFILL_MODES:
        raise MalformedResponse("fulfill")
    event = optional_str(node, "event")
    ranges = required_list(node, "eta_hours") if "eta_hours" in node else []
    happened = required_pair(node, "happened_hours") if event else None
    return ScenarioSpec(
        name=required_str(node, "name"),
        count=required_int(node, "count"),
        fulfill=fulfill,
        tracking=required_bool(node, "tracking"),
        event=event,
        min_quantity=required_int(node, "min_quantity") if "min_quantity" in node else 1,
        happened_hours=happened,
        eta_hours=tuple(as_pair(item, "eta_hours") for item in ranges),
        eta_same_day=node.get("eta_same_day") is True,
    )


def parse_state_event(node: JsonObject) -> StateEvent:
    eta = node.get("eta_hours")
    return StateEvent(
        status=required_str(node, "status"),
        eta_hours=eta if isinstance(eta, int) else None,
        same_day=required_bool(node, "same_day"),
    )


def parse_config(root: JsonObject) -> DistributionConfig:
    state = required_object(root, "set_state")
    events = required_object(state, "events")
    refresh = required_object(root, "refresh_eta")
    return DistributionConfig(
        version=required_str(root, "version"),
        seed=required_int(root, "seed"),
        plan_tag=required_str(root, "plan_tag"),
        carrier=required_str(root, "carrier"),
        tracking_prefix=required_str(root, "tracking_prefix"),
        tracking_url_base=required_str(root, "tracking_url_base"),
        canary_prefix=required_str(root, "canary_prefix"),
        note_template=required_str(root, "note_template"),
        scenarios=tuple(
            parse_scenario(node)
            for node in object_items(required_list(root, "scenarios"), "scenarios")
        ),
        stale_grace_minutes=required_int(refresh, "stale_grace_minutes"),
        eta_days_min=required_int(refresh, "eta_days_min"),
        eta_days_max=required_int(refresh, "eta_days_max"),
        set_state_happened_hours=required_int(state, "happened_hours"),
        set_state_events={
            name: parse_state_event(node)
            for name, node in ((key, optional_object(events, key)) for key in events)
            if node is not None
        },
    )


def load_config() -> DistributionConfig:
    text = resources.files("gisting.shopify").joinpath(CONFIG_FILE).read_text(encoding="utf-8")
    root: Json = json.loads(text)
    if not isinstance(root, dict):
        raise MalformedResponse(CONFIG_FILE)
    return parse_config(root)
