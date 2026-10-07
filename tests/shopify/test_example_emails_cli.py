import json
import subprocess
import sys
from pathlib import Path

import pytest
from shipment_support import entry, make_plan

from gisting.shopify.cli import main
from gisting.shopify.demo_email import demo_email
from gisting.shopify.plan import dump_plan

SECRET = "example-emails-cli-secret"
PLACEHOLDER = "xxxxxxxxxx@orders.example.com"


def example(order: str | None, name: str) -> dict[str, str]:
    row = {"id": name, "label_key": f"try.example.{name}"}
    return row if order is None else {**row, "order": order, "email": PLACEHOLDER}


def write_orders(tmp_path: Path, *orders: str | None) -> Path:
    rows = [example(order, f"row{index}") for index, order in enumerate(orders)]
    path = tmp_path / "example_orders.json"
    path.write_text(json.dumps({"examples": rows}, indent=2) + "\n")
    return path


@pytest.fixture
def setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("GISTING_EMAIL_SECRET", "placeholder")
    monkeypatch.delenv("GISTING_EMAIL_SECRET")
    (tmp_path / "empty.env").write_text("")
    (tmp_path / "plan.json").write_text(
        dump_plan(make_plan(entry(1006, "IN_TRANSIT"), entry(1022, "UNFULFILLED")))
    )
    return tmp_path


def run(tmp_path: Path, orders: Path, *extra: str) -> int:
    argv = [
        "fill-example-emails",
        "--orders",
        str(orders),
        "--plan",
        str(tmp_path / "plan.json"),
        "--env-file",
        str(tmp_path / "empty.env"),
        *extra,
    ]
    return main(argv)


def test_every_order_row_gets_its_demo_email_and_other_rows_are_untouched(
    setup: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("GISTING_EMAIL_SECRET", SECRET)
    orders = write_orders(setup, "#1006", "1022", None)
    assert run(setup, orders) == 0
    rows = json.loads(orders.read_text())["examples"]
    assert rows[0]["email"] == demo_email(SECRET, "#1006")
    assert rows[1]["email"] == demo_email(SECRET, "#1022")
    assert "email" not in rows[2]
    assert rows[0]["label_key"] == "try.example.row0"
    assert orders.read_text().endswith("}\n")
    captured = capsys.readouterr()
    assert captured.out.splitlines() == ["#1006 filled", "#1022 filled"]
    assert SECRET not in captured.out + captured.err
    assert "@" not in captured.out + captured.err


def test_running_twice_gives_the_same_file(setup: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GISTING_EMAIL_SECRET", SECRET)
    orders = write_orders(setup, "#1006")
    run(setup, orders)
    first = orders.read_text()
    run(setup, orders)
    assert orders.read_text() == first


def test_the_secret_is_read_from_the_env_file(setup: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (setup / "with-secret.env").write_text(f"GISTING_EMAIL_SECRET={SECRET}\n")
    orders = write_orders(setup, "#1006")
    assert run(setup, orders, "--env-file", str(setup / "with-secret.env")) == 0
    assert json.loads(orders.read_text())["examples"][0]["email"] == demo_email(SECRET, "#1006")


def test_a_missing_secret_exits_non_zero_names_only_the_variable_and_writes_nothing(
    setup: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    orders = write_orders(setup, "#1006")
    before = orders.read_text()
    assert run(setup, orders) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "gisting.shopify: GISTING_EMAIL_SECRET is not set\n"
    assert orders.read_text() == before


@pytest.mark.parametrize("order", ["#1001", "#1103", "#9999", "abc"])
def test_an_order_outside_the_plan_is_refused_and_nothing_is_written(
    order: str, setup: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("GISTING_EMAIL_SECRET", SECRET)
    orders = write_orders(setup, "#1006", order)
    before = orders.read_text()
    assert run(setup, orders) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert SECRET not in captured.err
    assert orders.read_text() == before


@pytest.mark.parametrize(
    "text",
    [
        "not json",
        "[]",
        "{}",
        '{"examples": {}}',
        '{"examples": [1]}',
        '{"examples": [{"order": 1006}]}',
    ],
)
def test_a_malformed_orders_file_is_a_usage_error(
    text: str, setup: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GISTING_EMAIL_SECRET", SECRET)
    orders = setup / "example_orders.json"
    orders.write_text(text)
    assert run(setup, orders) == 2
    assert orders.read_text() == text


def test_a_file_without_any_order_row_is_a_usage_error(
    setup: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GISTING_EMAIL_SECRET", SECRET)
    assert run(setup, write_orders(setup, None)) == 2


def test_a_missing_orders_file_is_a_usage_error(
    setup: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GISTING_EMAIL_SECRET", SECRET)
    assert run(setup, setup / "none.json") == 2


def test_the_committed_example_orders_are_in_the_committed_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GISTING_EMAIL_SECRET", SECRET)
    repo = Path(__file__).resolve().parents[2]
    copy = tmp_path / "example_orders.json"
    copy.write_text((repo / "apps/web/data/example_orders.json").read_text())
    argv = [
        "fill-example-emails",
        "--orders",
        str(copy),
        "--plan",
        str(repo / "data/demo-orders/shipment-plan-v1.json"),
    ]
    assert main([*argv, "--env-file", str(tmp_path / "missing.env")]) == 2
    (tmp_path / "e.env").write_text("")
    assert main([*argv, "--env-file", str(tmp_path / "e.env")]) == 0
    emails = [row.get("email") for row in json.loads(copy.read_text())["examples"]]
    assert emails == [demo_email(SECRET, "#1006"), demo_email(SECRET, "#1022"), None]


def test_demo_emails_still_works_next_to_the_new_command(
    setup: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GISTING_EMAIL_SECRET", SECRET)
    done = subprocess.run(
        [
            sys.executable,
            "-m",
            "gisting.shopify",
            "demo-emails",
            "--env-file",
            str(setup / "empty.env"),
        ],
        input='{"order_number": "#1042"}\n',
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0
    assert json.loads(done.stdout)["email"] == demo_email(SECRET, "#1042")


def test_rows_key_fills_orders_and_preserves_the_document(
    setup: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("GISTING_EMAIL_SECRET", SECRET)
    orders = setup / "public_orders.json"
    row = example("#1006", "in-transit")
    document = {"orders": [row], "other": "preserved"}
    orders.write_text(json.dumps(document))
    assert run(setup, orders, "--rows-key", "orders") == 0
    row["email"] = demo_email(SECRET, "#1006")
    assert json.loads(orders.read_text()) == document
    captured = capsys.readouterr()
    assert captured.out == "#1006 filled\n"
    assert SECRET not in captured.out + captured.err


@pytest.mark.parametrize("text", ['{"orders": {}}', '{"orders": [1]}', '{"examples": []}'])
def test_rows_key_rejects_malformed_rows_without_writing(
    text: str, setup: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GISTING_EMAIL_SECRET", SECRET)
    orders = setup / "public_orders.json"
    orders.write_text(text)
    assert run(setup, orders, "--rows-key", "orders") == 2
    assert orders.read_text() == text
