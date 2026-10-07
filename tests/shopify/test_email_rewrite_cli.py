import json
from pathlib import Path

import pytest
from fakes.shopify import FakeOrder, FakeTransport
from shipment_support import NOW, SECRET, entry, make_plan

from gisting.shopify.demo_apply import Runtime, main
from gisting.shopify.demo_email import demo_email
from gisting.shopify.jsonvalue import JsonObject
from gisting.shopify.plan import dump_plan
from gisting.shopify.results import GraphQLError

OLD_EMAIL = "stale@orders.example.com"
COMMANDS = [["rewrite-emails"], []]


def run_cli(tmp_path: Path, fake: FakeTransport, command: list[str], *extra: str) -> int:
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(
        dump_plan(make_plan(entry(1002, "UNFULFILLED"), entry(1003, "UNFULFILLED")))
    )
    (tmp_path / "empty.env").write_text("")
    argv = [
        *command,
        "--plan",
        str(plan_file),
        "--env-file",
        str(tmp_path / "empty.env"),
        "--ledger",
        str(tmp_path / "ledger.jsonl"),
        *extra,
    ]
    return main(argv, Runtime(fake, lambda _s: None, lambda: NOW))


@pytest.mark.parametrize("command", COMMANDS)
@pytest.mark.parametrize("only", ["", "  ", "1002,"])
def test_an_empty_only_is_a_usage_error_with_no_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command: list[str], only: str
) -> None:
    monkeypatch.setenv("GISTING_EMAIL_SECRET", SECRET)
    fake = FakeTransport([FakeOrder(1002, email=OLD_EMAIL), FakeOrder(1003, email=OLD_EMAIL)])
    assert run_cli(tmp_path, fake, command, "--only", only) == 2
    assert fake.calls == []
    assert not (tmp_path / "ledger.jsonl").exists()


def test_a_dry_run_sends_no_mutation_to_a_transport_that_would_execute_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GISTING_EMAIL_SECRET", SECRET)
    orders = [FakeOrder(1002, email=OLD_EMAIL), FakeOrder(1003, email=OLD_EMAIL)]
    fake = FakeTransport(orders)
    assert run_cli(tmp_path, fake, ["rewrite-emails"], "--dry-run") == 0
    assert fake.writes == []
    assert all(order.email == OLD_EMAIL for order in orders)


def test_a_dry_run_with_a_refused_order_exits_non_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("GISTING_EMAIL_SECRET", SECRET)
    fake = FakeTransport([FakeOrder(1002, email=OLD_EMAIL, test=False), FakeOrder(1003)])
    assert run_cli(tmp_path, fake, ["rewrite-emails"], "--dry-run") == 1
    assert "被拒 1" in capsys.readouterr().out


def test_a_failure_detail_that_quotes_an_email_is_masked_everywhere(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("GISTING_EMAIL_SECRET", SECRET)
    expected = demo_email(SECRET, "#1002")
    message = f"Email {expected} is invalid, replacing {OLD_EMAIL}"
    errors: tuple[JsonObject, ...] = ({"field": None, "message": message},)
    fake = FakeTransport([FakeOrder(1002, email=OLD_EMAIL)])
    fake.fail("order_update", GraphQLError(errors, user_errors=True))
    assert run_cli(tmp_path, fake, ["rewrite-emails"], "--only", "1002") == 1
    captured = capsys.readouterr()
    ledger = (tmp_path / "ledger.jsonl").read_text()
    for email in (expected, OLD_EMAIL):
        assert email not in captured.out + captured.err + ledger
    result = next(json.loads(line) for line in ledger.splitlines() if '"result"' in line)
    assert "[email]" in result["detail"]
    assert "effect_observed=False" in result["detail"]
