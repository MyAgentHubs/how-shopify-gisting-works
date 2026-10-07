from pathlib import Path

import pytest
from fakes.shopify import FakeOrder, FakeTransport
from shipment_support import PLAN_TAG, SECRET, context, entry, fulfilled, make_plan

from gisting.shopify.apply_order import Status
from gisting.shopify.client import AdminClient
from gisting.shopify.demo_email import demo_email
from gisting.shopify.dry_run import dry_run, render_report
from gisting.shopify.order_state import OrderState
from gisting.shopify.plan import PlanEntry
from gisting.shopify.readonly import ReadOnlyTransport
from gisting.shopify.results import Cause, GraphQLError, NotExecuted, Uncertain
from gisting.shopify.run_plan import Pacing, RunStopped, paced, run_plan


def unfulfilled(count: int) -> tuple[list[FakeOrder], list[PlanEntry]]:
    orders = [FakeOrder(1002 + index) for index in range(count)]
    entries = [entry(1002 + index, "UNFULFILLED") for index in range(count)]
    return orders, entries


def test_paced_waits_between_batches_only() -> None:
    waits: list[float] = []
    items = list(paced(list(range(7)), Pacing(3, 75.0, waits.append)))
    assert items == list(range(7))
    assert waits == [75.0, 75.0]


def test_paced_waits_after_the_previous_item_was_handled() -> None:
    log: list[str] = []
    pacing = Pacing(2, 1.0, lambda _seconds: log.append("wait"))
    for item in paced(["a", "b", "c"], pacing):
        log.append(item)
    assert log == ["a", "b", "wait", "c"]


def test_run_applies_every_order_in_batches(tmp_path: Path) -> None:
    orders, entries = unfulfilled(7)
    fake = FakeTransport(orders)
    waits: list[float] = []
    ctx = context(tmp_path, fake, make_plan(*entries))
    outcomes = run_plan(ctx, entries, Pacing(5, 75.0, waits.append), max_failures=3)
    assert [outcome.status for outcome in outcomes] == [Status.APPLIED] * 7
    assert waits == [75.0]
    assert all(PLAN_TAG in order.tags for order in orders)


def test_unresolved_uncertain_stops_the_whole_run(tmp_path: Path) -> None:
    orders, entries = unfulfilled(3)
    fake = FakeTransport(orders)
    fake.fail("order_update", Uncertain("tls"), applied=True, skip=1)
    for call in range(3):
        fake.fail("order_state", Uncertain("tls"), skip=3 if call == 0 else 0)
    ctx = context(tmp_path, fake, make_plan(*entries))
    with pytest.raises(RunStopped) as stopped:
        run_plan(ctx, entries, Pacing(5, 0.0, lambda _s: None), max_failures=3)
    assert [o.status for o in stopped.value.outcomes] == [Status.APPLIED, Status.UNCERTAIN]
    assert PLAN_TAG not in orders[2].tags
    assert orders[2].note == "seed note"


def test_resolved_uncertain_does_not_stop_the_run(tmp_path: Path) -> None:
    orders, entries = unfulfilled(2)
    fake = FakeTransport(orders)
    fake.fail("order_update", Uncertain("tls"), applied=False)
    ctx = context(tmp_path, fake, make_plan(*entries))
    outcomes = run_plan(ctx, entries, Pacing(5, 0.0, lambda _s: None), max_failures=3)
    assert [o.status for o in outcomes] == [Status.UNCERTAIN_RESOLVED, Status.APPLIED]


def test_consecutive_failures_stop_the_run(tmp_path: Path) -> None:
    orders, entries = unfulfilled(4)
    fake = FakeTransport(orders)
    for _ in range(4):
        fake.fail("order_update", GraphQLError(({"message": "denied"},)))
    ctx = context(tmp_path, fake, make_plan(*entries))
    with pytest.raises(RunStopped) as stopped:
        run_plan(ctx, entries, Pacing(5, 0.0, lambda _s: None), max_failures=2)
    assert len(stopped.value.outcomes) == 2
    assert len(fake.writes) == 2


def test_read_only_transport_refuses_mutations() -> None:
    fake = FakeTransport([FakeOrder(1002)])
    client = AdminClient(ReadOnlyTransport(fake))
    state = client.fetch_order("1002")
    assert isinstance(state, OrderState)
    verified = client.writable(state)
    assert not isinstance(verified, NotExecuted)
    result = client.write(verified, "tags_add", {"id": state.id, "tags": ["x"]})
    assert result == NotExecuted(Cause.READ_ONLY, "tags_add")
    assert fake.writes == []


def test_dry_run_reports_without_any_write(tmp_path: Path) -> None:
    orders = [FakeOrder(1002), FakeOrder(1003, quantity=2), FakeOrder(1004)]
    shipped = entry(1003, "IN_TRANSIT", quantity=2)
    fulfilled(orders[1], shipped)
    plan_entries = [
        entry(1002, "IN_TRANSIT"),
        entry(1003, "UNFULFILLED", quantity=2),
        entry(1004, "UNFULFILLED"),
    ]
    orders[2].tags.append(PLAN_TAG)
    fake = FakeTransport(orders)
    plan = make_plan(*plan_entries)
    ctx = context(tmp_path, fake, plan)
    rows = dry_run(ctx.client, plan, plan_entries, Pacing(5, 0.0, lambda _s: None), SECRET)
    text = render_report(rows, 100)
    assert fake.writes == []
    assert "只读" in text
    assert "核对订单 3 / 计划 100" in text
    assert "IN_TRANSIT 1" in text
    assert "已发货的订单无法再按计划改为未发货" in text
    assert "已带标签，将跳过" in text
    assert "创建发货" in text
    assert "写入物流事件 IN_TRANSIT" in text
    assert "#1002 IN_TRANSIT (现状 UNFULFILLED) [email: missing]" in text
    assert "只以备注" not in text


def test_dry_run_shows_only_five_examples(tmp_path: Path) -> None:
    orders, entries = unfulfilled(8)
    plan = make_plan(*entries)
    ctx = context(tmp_path, FakeTransport(orders), plan)
    rows = dry_run(ctx.client, plan, entries, Pacing(5, 0.0, lambda _s: None), SECRET)
    section = render_report(rows, 8).split("示例")[1]
    assert section.count("UNFULFILLED (现状") == 5


def test_dry_run_reports_unverifiable_orders(tmp_path: Path) -> None:
    fake = FakeTransport([FakeOrder(1002)])
    for _ in range(3):
        fake.fail("order_state", Uncertain("tls"))
    planned = entry(1002, "UNFULFILLED")
    plan = make_plan(planned)
    ctx = context(tmp_path, fake, plan)
    rows = dry_run(ctx.client, plan, [planned], Pacing(5, 0.0, lambda _s: None), SECRET)
    assert "无法核对 1" in render_report(rows, 1)


def test_dry_run_flags_non_test_orders(tmp_path: Path) -> None:
    fake = FakeTransport([FakeOrder(1002, test=False)])
    planned = entry(1002, "UNFULFILLED")
    plan = make_plan(planned)
    ctx = context(tmp_path, fake, plan)
    rows = dry_run(ctx.client, plan, [planned], Pacing(5, 0.0, lambda _s: None), SECRET)
    assert "拒绝写入: not_test_order" in render_report(rows, 1)


def test_dry_run_shows_email_match_state_without_the_value(tmp_path: Path) -> None:
    good = FakeOrder(1002)
    good.email = demo_email(SECRET, "#1002")
    bad = FakeOrder(1003)
    bad.email = "someone@elsewhere.test"
    entries = [entry(1002, "UNFULFILLED"), entry(1003, "UNFULFILLED"), entry(1004, "UNFULFILLED")]
    plan = make_plan(*entries)
    ctx = context(tmp_path, FakeTransport([good, bad, FakeOrder(1004)]), plan)
    text = render_report(
        dry_run(ctx.client, plan, entries, Pacing(5, 0.0, lambda _s: None), SECRET), 3
    )
    assert "#1002 UNFULFILLED (现状 UNFULFILLED) [email: matches]" in text
    assert "[email: mismatch]" in text
    assert "[email: missing]" in text
    assert "@" not in text
