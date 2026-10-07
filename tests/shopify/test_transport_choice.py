from pathlib import Path

import pytest
from shipment_support import entry, make_plan

from gisting.shopify.cli_transport import CliTransport
from gisting.shopify.demo_apply import (
    CLIENT_SECRET_ENV,
    UsageError,
    apply_parser,
    batch_wait,
    build_transport,
    main,
    set_state_parser,
)
from gisting.shopify.http_transport import HttpTransport
from gisting.shopify.plan import dump_plan


def test_http_is_the_default_transport_with_short_batch_wait() -> None:
    args = apply_parser().parse_args([])
    assert args.transport == "http"
    assert batch_wait(args) == 10.0
    assert set_state_parser().parse_args(["1002", "delivered"]).transport == "http"


def test_cli_transport_keeps_the_long_batch_wait() -> None:
    args = apply_parser().parse_args(["--transport", "cli"])
    assert batch_wait(args) == 75.0
    assert isinstance(build_transport(args), CliTransport)


def test_explicit_batch_wait_wins_for_both_transports() -> None:
    for name in ("http", "cli"):
        args = apply_parser().parse_args(["--transport", name, "--batch-wait", "3"])
        assert batch_wait(args) == 3.0


def test_http_transport_is_built_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(CLIENT_SECRET_ENV, "fake-secret")
    assert isinstance(build_transport(apply_parser().parse_args([])), HttpTransport)


def test_missing_client_secret_is_a_usage_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(CLIENT_SECRET_ENV, raising=False)
    with pytest.raises(UsageError):
        build_transport(apply_parser().parse_args([]))


def test_main_reports_missing_secret_without_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv(CLIENT_SECRET_ENV, raising=False)
    monkeypatch.setenv("GISTING_EMAIL_SECRET", "unit")
    plan = tmp_path / "plan.json"
    plan.write_text(dump_plan(make_plan(entry(1002, "UNFULFILLED"))))
    (tmp_path / "empty.env").write_text("")
    argv = ["--dry-run", "--plan", str(plan), "--env-file", str(tmp_path / "empty.env")]
    assert main(argv) == 2
    assert CLIENT_SECRET_ENV in capsys.readouterr().err
