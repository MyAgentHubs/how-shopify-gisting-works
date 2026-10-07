import json
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest
from eta_refresh_support import NEW_ETA, OLD_ETA, seeded
from fakes.shopify import FakeTransport
from shipment_support import NOW, SECRET, entry, make_plan

from gisting.shopify import demo_apply
from gisting.shopify.demo_apply import Runtime, main
from gisting.shopify.demo_config import load_config
from gisting.shopify.plan import ShipmentPlan, format_time
from gisting.shopify.results import Uncertain


@pytest.fixture
def offline_inputs(monkeypatch: pytest.MonkeyPatch) -> None:
    def inputs(_path: Path, _env: Path | None) -> tuple[ShipmentPlan, str]:
        return make_plan(
            entry(1006, "IN_TRANSIT"),
            entry(1014, "IN_TRANSIT"),
            entry(1020, "DELIVERED"),
            entry(1021, "UNFULFILLED"),
        ), SECRET

    monkeypatch.setattr(demo_apply, "load_inputs", inputs)


def run_cli(tmp_path: Path, fake: FakeTransport, extra: list[str]) -> int:
    return main(
        ["refresh-eta", "--ledger", str(tmp_path / "ledger.jsonl"), *extra],
        Runtime(fake, lambda _: None, lambda: NOW),
    )


@pytest.mark.usefixtures("offline_inputs")
@pytest.mark.parametrize("selector", [["#1006"], ["--orders", "#1006,#1014"], ["--all-stale"]])
def test_cli_dry_run_reports_old_and_new_without_writes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], selector: list[str]
) -> None:
    fake = FakeTransport([seeded(1006)[1], seeded(1014)[1], seeded(1020, "DELIVERED")[1]])
    assert run_cli(tmp_path, fake, [*selector, "--dry-run"]) == 0
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert captured.err == ""
    assert "stopped" not in report
    assert report["orders"][0] == {
        "order": "#1006",
        "result": "would_write",
        "old_eta": OLD_ETA,
        "new_eta": NEW_ETA,
        "detail": "",
    }
    assert report["summary"]["would_write"] == (1 if selector == ["#1006"] else 2)
    assert fake.writes == []
    records = [json.loads(line) for line in (tmp_path / "ledger.jsonl").read_text().splitlines()]
    assert all(record["kind"] == "refresh_eta_result" for record in records)


@pytest.mark.usefixtures("offline_inputs")
def test_all_stale_reads_mixed_set_and_only_writes_stale(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stale = seeded(1006)[1]
    fresh = seeded(1014)[1]
    fresh.fulfillments[0].estimated_delivery_at = NEW_ETA
    fake = FakeTransport([stale, fresh, seeded(1020, "DELIVERED")[1]])
    assert run_cli(tmp_path, fake, ["--all-stale"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["summary"] == {"written": 1, "skipped_fresh": 1, "skipped_no_eta": 1}
    assert len(fake.writes) == 1
    assert [row["order"] for row in report["orders"]] == ["#1006", "#1014", "#1020"]


@pytest.mark.usefixtures("offline_inputs")
@pytest.mark.parametrize(
    "extra",
    [
        [],
        ["#1006", "--orders", "#1014"],
        ["#1006", "--all-stale"],
        ["--orders", "#1006", "--all-stale"],
        ["#9999"],
        ["--orders", ""],
        ["--orders", "#1006,#9999"],
        ["bad"],
        ["#1006,#1014"],
    ],
)
def test_selector_usage_errors_never_read_or_write(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], extra: list[str]
) -> None:
    fake = FakeTransport([seeded()[1]])
    assert run_cli(tmp_path, fake, extra) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err
    assert fake.calls == []


@pytest.mark.usefixtures("offline_inputs")
def test_cli_mismatch_exits_one(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    order = seeded()[1]
    order.fulfillments[0].update_eta = False
    fake = FakeTransport([order])
    assert run_cli(tmp_path, fake, ["#1006"]) == 1
    assert json.loads(capsys.readouterr().out)["summary"] == {"mismatch": 1}
    assert len(fake.writes) == 1


@pytest.mark.usefixtures("offline_inputs")
def test_uncertain_stops_cli_batch_and_exits_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = FakeTransport([seeded(1006)[1], seeded(1014)[1]])
    fake.fail("fulfillment_event_create", Uncertain("lost response"), applied=True)
    assert run_cli(tmp_path, fake, ["--orders", "#1006,#1014"]) == 1
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert report["summary"] == {"uncertain": 1}
    assert report["stopped"] == "#1006: uncertain; outcome unresolved"
    assert captured.err == f"demo_apply: run stopped: {report['stopped']}\n"
    assert all(call.variables.get("query") != "name:#1014" for call in fake.calls)
    assert len(fake.writes) == 1


@pytest.mark.usefixtures("offline_inputs")
def test_cli_paces_batches(tmp_path: Path) -> None:
    fake = FakeTransport([seeded(1006)[1], seeded(1014)[1]])
    sleeps: list[float] = []
    assert (
        main(
            [
                "refresh-eta",
                "--orders",
                "1006,1014",
                "--ledger",
                str(tmp_path / "ledger.jsonl"),
                "--batch-size",
                "1",
                "--batch-wait",
                "7",
            ],
            Runtime(fake, sleeps.append, lambda: NOW),
        )
        == 0
    )
    assert sleeps == [7]


@pytest.mark.usefixtures("offline_inputs")
def test_cli_failure_limit_reports_stop_without_attempting_next_order(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    refused = seeded(1006)[1]
    refused.test = False
    fake = FakeTransport([refused, seeded(1014)[1]])
    assert run_cli(tmp_path, fake, ["--orders", "#1006,#1014", "--max-failures", "1"]) == 1
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert report["summary"] == {"refused": 1}
    assert report["stopped"] == "#1006: refused; 1 consecutive failures"
    assert captured.err == f"demo_apply: run stopped: {report['stopped']}\n"
    assert [row["order"] for row in report["orders"]] == ["#1006"]
    assert [call.variables["query"] for call in fake.calls] == ["name:#1006"]
    assert fake.writes == []


@pytest.mark.usefixtures("offline_inputs")
@pytest.mark.parametrize("raw", ["0", "31", "1.5", "tomorrow"])
def test_invalid_horizon_is_usage_error_before_any_reads(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], raw: str
) -> None:
    fake = FakeTransport([seeded()[1]])
    assert run_cli(tmp_path, fake, ["#1006", "--eta-days", raw]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "--eta-days must be an integer in the range 1..30" in captured.err
    assert fake.calls == []


@pytest.mark.usefixtures("offline_inputs")
def test_force_all_stale_is_usage_error_before_reads(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = FakeTransport([seeded()[1]])
    assert run_cli(tmp_path, fake, ["--all-stale", "--force", "--dry-run"]) == 2
    assert "--force cannot be combined with --all-stale" in capsys.readouterr().err
    assert fake.calls == []


@pytest.mark.usefixtures("offline_inputs")
@pytest.mark.parametrize("selector", [["#1006"], ["--orders", "#1006,#1014"]])
@pytest.mark.parametrize("dry_run", [False, True])
def test_cli_force_horizon_reaches_selected_orders(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], selector: list[str], dry_run: bool
) -> None:
    orders = [seeded(number)[1] for number in (1006, 1014)]
    for order in orders:
        order.fulfillments[0].estimated_delivery_at = NEW_ETA
    fake = FakeTransport(orders)
    extra = [*selector, "--force", "--eta-days", "7"]
    assert run_cli(tmp_path, fake, [*extra, *(["--dry-run"] if dry_run else [])]) == 0
    report = json.loads(capsys.readouterr().out)
    count = 1 if selector == ["#1006"] else 2
    assert report["summary"] == {"would_write" if dry_run else "written": count}
    assert all(row["new_eta"] == format_time(NOW + timedelta(days=7)) for row in report["orders"])
    assert len(fake.writes) == (0 if dry_run else count)


@pytest.mark.usefixtures("offline_inputs")
def test_cli_all_stale_accepts_horizon(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    fresh = seeded(1014)[1]
    fresh.fulfillments[0].estimated_delivery_at = NEW_ETA
    fake = FakeTransport([seeded()[1], fresh, seeded(1020, "DELIVERED")[1]])
    assert run_cli(tmp_path, fake, ["--all-stale", "--eta-days", "7", "--dry-run"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["summary"] == {"would_write": 1, "skipped_fresh": 1, "skipped_no_eta": 1}
    assert fake.writes == []


@pytest.mark.usefixtures("offline_inputs")
def test_horizon_range_comes_from_config(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    config = replace(load_config(), eta_days_min=3, eta_days_max=5)
    monkeypatch.setattr(demo_apply, "load_config", lambda: config)
    fake = FakeTransport([seeded()[1]])
    assert run_cli(tmp_path, fake, ["#1006", "--eta-days", "7"]) == 2
    assert "range 3..5" in capsys.readouterr().err
    assert fake.calls == []
