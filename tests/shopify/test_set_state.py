import json
from pathlib import Path

import pytest
from fakes.shopify import FakeOrder, FakeTransport
from shipment_support import NOW, PLAN_TAG, SECRET, context, entry, make_plan

from gisting.shopify.apply_order import ApplyContext, OrderOutcome, Status, apply_order
from gisting.shopify.demo_apply import Runtime, main
from gisting.shopify.demo_config import load_config
from gisting.shopify.plan import dump_plan
from gisting.shopify.results import Uncertain
from gisting.shopify.set_state import UnknownOrder, UnknownState, set_state


def applied_order(
    tmp_path: Path, scenario: str, quantity: int = 1
) -> tuple[FakeOrder, FakeTransport, ApplyContext]:
    order = FakeOrder(1042, quantity=quantity)
    planned = entry(1042, scenario, quantity=quantity)
    fake = FakeTransport([order])
    ctx = context(tmp_path, fake, make_plan(planned))
    assert apply_order(ctx, planned).status is Status.APPLIED
    return order, fake, ctx


def test_delivered_adds_event_to_existing_fulfilment(tmp_path: Path) -> None:
    order, fake, ctx = applied_order(tmp_path, "IN_TRANSIT")
    before = len(fake.writes)
    outcome = set_state(ctx, load_config(), "1042", "delivered")
    assert outcome.status is Status.APPLIED
    assert [r.name for r in fake.writes[before:]] == ["fulfillment_event_create"]
    shipment = order.fulfillments[0]
    assert shipment.events[-1]["status"] == "DELIVERED"
    assert shipment.events[-1]["happenedAt"] == "2026-10-02T09:00:00Z"
    assert shipment.delivered_at == "2026-10-02T09:00:00Z"


def test_set_state_twice_is_a_no_op(tmp_path: Path) -> None:
    _, fake, ctx = applied_order(tmp_path, "IN_TRANSIT")
    assert set_state(ctx, load_config(), "#1042", "delivered").status is Status.APPLIED
    before = len(fake.writes)
    outcome = set_state(ctx, load_config(), "1042", "delivered")
    assert outcome.status is Status.SKIPPED_SAME_STATE
    assert outcome.steps == ()
    assert outcome.detail == ("Nothing was written because the order already has the target state.")
    assert len(fake.writes) == before


def test_set_state_ships_an_unfulfilled_order_first(tmp_path: Path) -> None:
    order, fake, ctx = applied_order(tmp_path, "UNFULFILLED", quantity=2)
    before = len(fake.writes)
    outcome = set_state(ctx, load_config(), "1042", "out-for-delivery")
    assert outcome.status is Status.APPLIED
    assert [r.name for r in fake.writes[before:]] == [
        "fulfillment_create",
        "fulfillment_event_create",
    ]
    assert order.fulfillments[0].quantity == 2
    assert str(order.fulfillments[0].tracking[0]["number"]).startswith("TP-")
    assert order.fulfillments[0].estimated_delivery_at == "2026-10-02T13:00:00Z"
    assert order.status == "FULFILLED"


def test_set_state_keeps_the_partial_quantity(tmp_path: Path) -> None:
    order, _, ctx = applied_order(tmp_path, "PARTIALLY_FULFILLED", quantity=3)
    assert set_state(ctx, load_config(), "1042", "delayed").status is Status.APPLIED
    assert order.fulfillments[0].quantity == 2
    assert order.status == "PARTIALLY_FULFILLED"


def test_set_state_refuses_orders_the_plan_has_not_touched(tmp_path: Path) -> None:
    order = FakeOrder(1042)
    fake = FakeTransport([order])
    ctx = context(tmp_path, fake, make_plan(entry(1042, "IN_TRANSIT")))
    outcome = set_state(ctx, load_config(), "1042", "delivered")
    assert outcome.status is Status.REFUSED
    assert fake.writes == []


def test_set_state_refuses_non_test_orders(tmp_path: Path) -> None:
    order = FakeOrder(1042, test=False)
    order.tags.append(PLAN_TAG)
    fake = FakeTransport([order])
    ctx = context(tmp_path, fake, make_plan(entry(1042, "IN_TRANSIT")))
    outcome = set_state(ctx, load_config(), "1042", "delivered")
    assert outcome.status is Status.REFUSED
    assert fake.writes == []


def test_unknown_state_and_order_raise(tmp_path: Path) -> None:
    ctx = context(tmp_path, FakeTransport([]), make_plan(entry(1042, "IN_TRANSIT")))
    with pytest.raises(UnknownState):
        set_state(ctx, load_config(), "1042", "teleported")
    with pytest.raises(UnknownOrder):
        set_state(ctx, load_config(), "1043", "delivered")


def test_unfulfilled_is_not_a_settable_state(tmp_path: Path) -> None:
    ctx = context(tmp_path, FakeTransport([]), make_plan(entry(1042, "IN_TRANSIT")))
    with pytest.raises(UnknownState):
        set_state(ctx, load_config(), "1042", "unfulfilled")


def write_plan(tmp_path: Path, *orders: int) -> Path:
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(dump_plan(make_plan(*(entry(n, "IN_TRANSIT") for n in orders))))
    (tmp_path / "empty.env").write_text("")
    return plan_file


def run_cli(tmp_path: Path, fake: FakeTransport, *extra: str, plan: Path | None = None) -> int:
    plan_file = plan or write_plan(tmp_path, 1002, 1003)
    runtime = Runtime(fake, lambda _s: None, lambda: NOW)
    argv = [
        "--plan",
        str(plan_file),
        "--env-file",
        str(tmp_path / "empty.env"),
        "--ledger",
        str(tmp_path / "ledger.jsonl"),
        *extra,
    ]
    return main(argv, runtime)


def test_cli_dry_run_is_read_only_and_needs_the_email_secret(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("GISTING_EMAIL_SECRET", SECRET)
    fake = FakeTransport([FakeOrder(1002), FakeOrder(1003)])
    assert run_cli(tmp_path, fake, "--dry-run", "--only", "1002") == 0
    captured = capsys.readouterr()
    assert "核对订单 1 / 计划 2" in captured.out
    assert fake.writes == []
    assert not (tmp_path / "ledger.jsonl").exists()


def test_cli_apply_writes_ledger_and_prints_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("GISTING_EMAIL_SECRET", SECRET)
    fake = FakeTransport([FakeOrder(1002), FakeOrder(1003)])
    assert run_cli(tmp_path, fake) == 0
    assert json.loads(capsys.readouterr().out) == {"applied": 2}
    lines = (tmp_path / "ledger.jsonl").read_text().splitlines()
    assert sum('"kind": "result"' in line for line in lines) == 2


def test_cli_apply_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("GISTING_EMAIL_SECRET", SECRET)
    fake = FakeTransport([FakeOrder(1002), FakeOrder(1003)])
    run_cli(tmp_path, fake)
    capsys.readouterr()
    writes = len(fake.writes)
    assert run_cli(tmp_path, fake) == 0
    assert json.loads(capsys.readouterr().out) == {"skipped_tagged": 2}
    assert len(fake.writes) == writes


def test_cli_without_secret_is_a_usage_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("GISTING_EMAIL_SECRET", "x")
    monkeypatch.delenv("GISTING_EMAIL_SECRET")
    assert run_cli(tmp_path, FakeTransport([])) == 2
    assert "GISTING_EMAIL_SECRET" in capsys.readouterr().err


def test_cli_unknown_only_order_is_a_usage_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GISTING_EMAIL_SECRET", SECRET)
    assert run_cli(tmp_path, FakeTransport([]), "--only", "9999") == 2


def test_cli_stops_and_reports_on_stderr_when_outcome_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("GISTING_EMAIL_SECRET", SECRET)
    fake = FakeTransport([FakeOrder(1002), FakeOrder(1003)])
    fake.fail("order_update", Uncertain("tls"), applied=True)
    for call in range(3):
        fake.fail("order_state", Uncertain("tls"), skip=1 if call == 0 else 0)
    assert run_cli(tmp_path, fake) == 1
    captured = capsys.readouterr()
    assert "run stopped" in captured.err
    assert json.loads(captured.out) == {"uncertain": 1}
    assert "uncertain" in (tmp_path / "ledger.jsonl").read_text()


def test_cli_set_state_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("GISTING_EMAIL_SECRET", SECRET)
    order = FakeOrder(1002)
    fake = FakeTransport([order, FakeOrder(1003)])
    assert run_cli(tmp_path, fake) == 0
    capsys.readouterr()
    runtime = Runtime(fake, lambda _s: None, lambda: NOW)
    argv = [
        "set-state",
        "1002",
        "delivered",
        "--plan",
        str(tmp_path / "plan.json"),
        "--env-file",
        str(tmp_path / "empty.env"),
        "--ledger",
        str(tmp_path / "ledger.jsonl"),
    ]
    assert main(argv, runtime) == 0
    assert json.loads(capsys.readouterr().out) == {"applied": 1}
    assert order.fulfillments[0].events[-1]["status"] == "DELIVERED"


def test_outcome_type_is_exported() -> None:
    assert OrderOutcome("#1", "X", Status.APPLIED).detail == ""


def test_cli_set_state_same_state_skips_without_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("GISTING_EMAIL_SECRET", SECRET)
    _, fake, _ = applied_order(tmp_path, "IN_TRANSIT")
    plan_file = write_plan(tmp_path, 1042)
    before = list(fake.writes)
    runtime = Runtime(fake, lambda _s: None, lambda: NOW)
    argv = [
        "set-state",
        "1042",
        "in-transit",
        "--plan",
        str(plan_file),
        "--env-file",
        str(tmp_path / "empty.env"),
        "--ledger",
        str(tmp_path / "ledger.jsonl"),
    ]
    assert main(argv, runtime) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {"skipped_same_state": 1}
    assert captured.err == ""
    assert fake.writes == before
