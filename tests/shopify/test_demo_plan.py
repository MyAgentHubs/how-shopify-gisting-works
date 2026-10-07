import json
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from gisting.shopify.demo_config import load_config
from gisting.shopify.demo_plan import main
from gisting.shopify.plan import (
    Offset,
    PlanEntry,
    ShipmentPlan,
    dump_plan,
    format_time,
    load_plan,
    resolve_offset,
)
from gisting.shopify.plan_build import OrderRef, build_plan

EXPECTED = {
    "UNFULFILLED": 25,
    "PARTIALLY_FULFILLED": 12,
    "IN_TRANSIT": 25,
    "OUT_FOR_DELIVERY": 10,
    "DELIVERED": 15,
    "ATTEMPTED_DELIVERY": 3,
    "DELAYED": 3,
    "FULFILLED_NO_TRACKING": 7,
}
NOW = datetime(2026, 10, 2, 10, 0, tzinfo=UTC)


def seed_orders() -> list[OrderRef]:
    return [OrderRef(f"#{1002 + index}", index % 4 + 1) for index in range(100)]


def make_plan(seed: int | None = None) -> ShipmentPlan:
    return build_plan(seed_orders(), load_config(), seed)


def test_distribution_matches_the_brief() -> None:
    counts = Counter(entry.scenario for entry in make_plan().entries)
    assert dict(counts) == EXPECTED
    assert sum(counts.values()) == 100


def test_every_order_appears_once() -> None:
    names = [entry.order for entry in make_plan().entries]
    assert names == [f"#{number}" for number in range(1002, 1102)]


def test_same_seed_gives_byte_identical_output() -> None:
    assert dump_plan(make_plan()) == dump_plan(make_plan())


def test_other_seed_changes_the_assignment() -> None:
    assert dump_plan(make_plan(1)) != dump_plan(make_plan(2))


def test_partial_fulfilment_only_from_multi_quantity_orders_and_ships_one_less() -> None:
    partial = [e for e in make_plan().entries if e.scenario == "PARTIALLY_FULFILLED"]
    assert len(partial) == 12
    assert all(entry.quantity >= 2 for entry in partial)
    assert all(entry.fulfill_quantity == entry.quantity - 1 for entry in partial)


def test_other_scenarios_ship_everything_or_nothing() -> None:
    for entry in make_plan().entries:
        if entry.scenario == "UNFULFILLED":
            assert entry.fulfill_quantity == 0
        elif entry.scenario != "PARTIALLY_FULFILLED":
            assert entry.fulfill_quantity == entry.quantity


def test_tracking_is_unique_and_shaped() -> None:
    entries = [e for e in make_plan().entries if e.tracking is not None]
    numbers = [e.tracking.number for e in entries if e.tracking]
    assert len(numbers) == len(set(numbers)) == 100 - 25 - 7
    for entry in entries:
        assert entry.tracking is not None
        assert entry.tracking.company == "Test Parcel"
        assert re.fullmatch(r"TP-\d{10}", entry.tracking.number)
        assert entry.tracking.url == f"https://tracking.example.com/{entry.tracking.number}"


def test_unshipped_and_untracked_scenarios_have_no_tracking_or_event() -> None:
    for entry in make_plan().entries:
        if entry.scenario in {"UNFULFILLED", "FULFILLED_NO_TRACKING"}:
            assert entry.tracking is None
            assert entry.event is None


def test_canaries_are_unique_and_shaped() -> None:
    canaries = [entry.canary for entry in make_plan().entries]
    assert len(set(canaries)) == 100
    assert all(re.fullmatch(r"GLR-[0-9A-F]{8}", canary) for canary in canaries)


def test_event_timing_by_scenario() -> None:
    by_scenario: dict[str, list[PlanEntry]] = {}
    for entry in make_plan().entries:
        by_scenario.setdefault(entry.scenario, []).append(entry)
    for entry in by_scenario["OUT_FOR_DELIVERY"]:
        assert entry.event is not None
        assert entry.event.estimated_delivery_at is not None
        assert entry.event.estimated_delivery_at.same_day
    for entry in by_scenario["DELIVERED"]:
        assert entry.event is not None
        assert resolve_offset(NOW, entry.event.happened_at) < NOW
    for entry in by_scenario["IN_TRANSIT"]:
        assert entry.event is not None and entry.event.estimated_delivery_at is not None
        assert resolve_offset(NOW, entry.event.estimated_delivery_at) > NOW
    delayed = [e.event.estimated_delivery_at for e in by_scenario["DELAYED"] if e.event]
    resolved = [resolve_offset(NOW, eta) for eta in delayed if eta is not None]
    assert any(moment < NOW for moment in resolved)
    assert any(moment > NOW for moment in resolved)


def test_all_happened_times_are_in_the_past() -> None:
    for entry in make_plan().entries:
        if entry.event is not None:
            assert resolve_offset(NOW, entry.event.happened_at) < NOW


def test_plan_file_contains_no_email() -> None:
    assert "@" not in dump_plan(make_plan())


def test_plan_round_trips_through_json() -> None:
    plan = make_plan()
    assert load_plan(dump_plan(plan)) == plan


def test_same_day_offset_never_crosses_midnight() -> None:
    late = datetime(2026, 10, 2, 22, 30, tzinfo=UTC)
    assert resolve_offset(late, Offset(0, 4, same_day=True)).date() == late.date()
    assert resolve_offset(NOW, Offset(0, 4, same_day=True)) == datetime(2026, 10, 2, 14, tzinfo=UTC)


def test_offsets_split_into_days_and_hours() -> None:
    assert Offset.from_hours(-50) == Offset(-2, -2)
    assert resolve_offset(NOW, Offset(-2, -2)) == datetime(2026, 9, 30, 8, tzinfo=UTC)
    assert format_time(NOW) == "2026-10-02T10:00:00Z"


def test_cli_writes_identical_bytes_twice(tmp_path: Path) -> None:
    snapshot = tmp_path / "orders.json"
    nodes = [
        {"name": order.name, "lineItems": {"nodes": [{"quantity": order.quantity}]}}
        for order in seed_orders()
    ]
    snapshot.write_text(json.dumps({"orders": nodes}))
    first, second = tmp_path / "a" / "plan.json", tmp_path / "b" / "plan.json"
    assert main(["--orders", str(snapshot), "--out", str(first)]) == 0
    assert main(["--orders", str(snapshot), "--out", str(second)]) == 0
    assert first.read_bytes() == second.read_bytes()
    assert load_plan(first.read_text()).entries[0].order == "#1002"
