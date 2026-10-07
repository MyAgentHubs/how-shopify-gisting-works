import json
from pathlib import Path

import pytest
from fakes.shopify import FakeOrder, FakeTransport
from shipment_support import NOW, SECRET, context, entry, make_plan

from gisting.shopify.apply_order import Status
from gisting.shopify.client import AdminClient
from gisting.shopify.demo_apply import Runtime, main
from gisting.shopify.demo_email import demo_email
from gisting.shopify.email_rewrite import rewrite_email
from gisting.shopify.email_rewrite_report import Verdict, dry_run_emails
from gisting.shopify.jsonvalue import JsonObject
from gisting.shopify.plan import dump_plan
from gisting.shopify.readonly import ReadOnlyTransport
from gisting.shopify.results import Cause, GraphQLError, NotExecuted, Uncertain
from gisting.shopify.run_plan import Pacing, RunStopped, run_plan

OLD_EMAIL = "stale@orders.example.com"


def stale(number: int, **fields: object) -> FakeOrder:
    order = FakeOrder(number, email=OLD_EMAIL)
    for key, value in fields.items():
        setattr(order, key, value)
    return order


def rewrite(tmp_path: Path, fake: FakeTransport, number: int = 1002) -> Status:
    planned = entry(number, "UNFULFILLED")
    ctx = context(tmp_path, fake, make_plan(planned))
    return rewrite_email(ctx, planned).status


def update_inputs(fake: FakeTransport) -> list[object]:
    return [call.variables["input"] for call in fake.writes]


def test_rewrite_sets_the_email_alone_and_reads_it_back(tmp_path: Path) -> None:
    order = stale(1002)
    fake = FakeTransport([order])
    assert rewrite(tmp_path, fake) == Status.APPLIED
    assert order.email == demo_email(SECRET, "#1002")
    assert update_inputs(fake) == [{"id": order.gid, "email": demo_email(SECRET, "#1002")}]
    assert order.note == "seed note"
    assert order.tags == ["gisting-batch-20260930-v1"]


def test_matching_email_is_skipped_without_a_write(tmp_path: Path) -> None:
    order = FakeOrder(1002, email=demo_email(SECRET, "#1002"))
    fake = FakeTransport([order])
    assert rewrite(tmp_path, fake) == Status.UNCHANGED
    assert fake.writes == []


def test_non_test_order_is_refused(tmp_path: Path) -> None:
    order = stale(1002, test=False)
    fake = FakeTransport([order])
    assert rewrite(tmp_path, fake) == Status.REFUSED
    assert fake.writes == []
    assert order.email == OLD_EMAIL


def test_order_without_the_batch_tag_is_refused(tmp_path: Path) -> None:
    order = stale(1002, tags=[])
    fake = FakeTransport([order])
    assert rewrite(tmp_path, fake) == Status.REFUSED
    assert fake.writes == []


def test_refused_order_is_not_skipped_even_when_email_matches(tmp_path: Path) -> None:
    order = FakeOrder(1002, email=demo_email(SECRET, "#1002"), test=False)
    assert rewrite(tmp_path, FakeTransport([order])) == Status.REFUSED


def test_wrong_store_is_refused(tmp_path: Path) -> None:
    fake = FakeTransport([stale(1002)], shop_domain="other.myshopify.com")
    assert rewrite(tmp_path, fake) == Status.REFUSED
    assert fake.writes == []


def test_readback_mismatch_is_a_failure(tmp_path: Path) -> None:
    order = stale(1002, email_write="alter")
    assert rewrite(tmp_path, FakeTransport([order])) == Status.FAILED


def test_uncertain_write_that_took_effect_is_confirmed_without_resending(tmp_path: Path) -> None:
    order = stale(1002)
    fake = FakeTransport([order])
    fake.fail("order_update", Uncertain("tls"), applied=True)
    assert rewrite(tmp_path, fake) == Status.APPLIED
    assert order.email == demo_email(SECRET, "#1002")
    assert len(fake.writes) == 1


def test_uncertain_write_that_did_not_land_is_retried_once(tmp_path: Path) -> None:
    order = stale(1002)
    fake = FakeTransport([order])
    fake.fail("order_update", Uncertain("tls"), applied=False)
    assert rewrite(tmp_path, fake) == Status.APPLIED
    assert order.email == demo_email(SECRET, "#1002")
    assert len(fake.writes) == 2


def test_second_uncertain_write_without_effect_is_unresolved(tmp_path: Path) -> None:
    order = stale(1002)
    fake = FakeTransport([order])
    fake.fail("order_update", Uncertain("tls"))
    fake.fail("order_update", Uncertain("tls"))
    assert rewrite(tmp_path, fake) == Status.UNCERTAIN
    assert len(fake.writes) == 2
    assert order.email == OLD_EMAIL


def test_unreadable_order_after_an_uncertain_write_is_unresolved(tmp_path: Path) -> None:
    fake = FakeTransport([stale(1002)])
    fake.fail("order_update", Uncertain("tls"), applied=True)
    for call in range(3):
        fake.fail("order_state", Uncertain("tls"), skip=1 if call == 0 else 0)
    assert rewrite(tmp_path, fake) == Status.UNCERTAIN
    assert len(fake.writes) == 1


def test_unresolved_uncertain_stops_the_run(tmp_path: Path) -> None:
    orders = [stale(1002), stale(1003)]
    fake = FakeTransport(orders)
    fake.fail("order_update", Uncertain("tls"))
    fake.fail("order_update", Uncertain("tls"))
    entries = [entry(1002, "UNFULFILLED"), entry(1003, "UNFULFILLED")]
    ctx = context(tmp_path, fake, make_plan(*entries))
    with pytest.raises(RunStopped) as stopped:
        run_plan(ctx, entries, Pacing(5, 0.0, lambda _s: None), 3, rewrite_email)
    assert [o.status for o in stopped.value.outcomes] == [Status.UNCERTAIN]
    assert orders[1].email == OLD_EMAIL


def test_write_refused_before_sending_is_refused_with_a_single_write(tmp_path: Path) -> None:
    order = stale(1002)
    fake = FakeTransport([order])
    fake.fail("order_update", NotExecuted(Cause.NETWORK))
    assert rewrite(tmp_path, fake) == Status.REFUSED
    assert len(fake.writes) == 1
    assert order.email == OLD_EMAIL


@pytest.mark.parametrize("applied", [True, False])
def test_user_errors_fail_but_the_order_is_read_back(tmp_path: Path, applied: bool) -> None:
    order = stale(1002)
    fake = FakeTransport([order])
    errors: tuple[JsonObject, ...] = ({"field": None, "message": "bad"},)
    fake.fail("order_update", GraphQLError(errors, user_errors=True), applied=applied)
    planned = entry(1002, "UNFULFILLED")
    outcome = rewrite_email(context(tmp_path, fake, make_plan(planned)), planned)
    assert outcome.status is Status.FAILED
    assert f"effect_observed={applied}" in outcome.detail
    assert len(fake.writes) == 1


def test_dry_run_reads_only_and_counts_each_verdict(tmp_path: Path) -> None:
    orders = [
        stale(1002),
        FakeOrder(1003, email=demo_email(SECRET, "#1003")),
        stale(1004, test=False),
    ]
    fake = FakeTransport(orders)
    client = AdminClient(ReadOnlyTransport(fake), sleep=lambda _s: None)
    entries = [entry(number, "UNFULFILLED") for number in (1002, 1003, 1004, 1005)]
    rows = dry_run_emails(client, entries, Pacing(5, 0.0, lambda _s: None), SECRET)
    assert [row.verdict for row in rows] == [
        Verdict.WILL_CHANGE,
        Verdict.MATCHED,
        Verdict.REFUSED,
        Verdict.REFUSED,
    ]
    assert rows[2].detail == Cause.NOT_TEST_ORDER.value
    assert all(call.name == "order_state" for call in fake.calls)


def write_plan(tmp_path: Path, *orders: int) -> Path:
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(dump_plan(make_plan(*(entry(n, "UNFULFILLED") for n in orders))))
    (tmp_path / "empty.env").write_text("")
    return plan_file


def run_cli(tmp_path: Path, fake: FakeTransport, *extra: str) -> int:
    runtime = Runtime(fake, lambda _s: None, lambda: NOW)
    argv = [
        "rewrite-emails",
        "--plan",
        str(write_plan(tmp_path, 1002, 1003)),
        "--env-file",
        str(tmp_path / "empty.env"),
        "--ledger",
        str(tmp_path / "ledger.jsonl"),
        *extra,
    ]
    return main(argv, runtime)


def test_cli_rewrites_every_order_and_never_prints_an_email(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("GISTING_EMAIL_SECRET", SECRET)
    orders = [stale(1002), stale(1003)]
    assert run_cli(tmp_path, FakeTransport(orders)) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {"applied": 2}
    ledger = (tmp_path / "ledger.jsonl").read_text()
    for order in orders:
        expected = demo_email(SECRET, order.name)
        assert order.email == expected
        assert expected not in captured.out + captured.err + ledger
        assert OLD_EMAIL not in captured.out + captured.err + ledger
    assert sum('"kind": "result"' in line for line in ledger.splitlines()) == 2


def test_cli_second_run_is_all_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("GISTING_EMAIL_SECRET", SECRET)
    fake = FakeTransport([stale(1002), stale(1003)])
    run_cli(tmp_path, fake)
    capsys.readouterr()
    writes = len(fake.writes)
    assert run_cli(tmp_path, fake) == 0
    assert json.loads(capsys.readouterr().out) == {"unchanged": 2}
    assert len(fake.writes) == writes


def test_cli_only_touches_the_named_order(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GISTING_EMAIL_SECRET", SECRET)
    orders = [stale(1002), stale(1003)]
    assert run_cli(tmp_path, FakeTransport(orders), "--only", "1003") == 0
    assert orders[0].email == OLD_EMAIL
    assert orders[1].email == demo_email(SECRET, "#1003")


def test_cli_dry_run_has_no_mutation_no_ledger_and_no_email_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("GISTING_EMAIL_SECRET", SECRET)
    orders = [stale(1002), FakeOrder(1003, email=demo_email(SECRET, "#1003"))]
    fake = FakeTransport(orders)
    assert run_cli(tmp_path, fake, "--dry-run") == 0
    out = capsys.readouterr().out
    assert "订单 2 / 计划 2，将改 1，已匹配 1，被拒 0，无法核对 0" in out
    assert [call.name for call in fake.calls] == ["order_state", "order_state"]
    assert not (tmp_path / "ledger.jsonl").exists()
    assert OLD_EMAIL not in out
    assert all(demo_email(SECRET, order.name) not in out for order in orders)
    assert orders[0].email == OLD_EMAIL


def test_cli_refusal_exits_non_zero_after_counting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("GISTING_EMAIL_SECRET", SECRET)
    fake = FakeTransport([stale(1002, test=False), stale(1003)])
    assert run_cli(tmp_path, fake) == 1
    assert json.loads(capsys.readouterr().out) == {"applied": 1, "refused": 1}
