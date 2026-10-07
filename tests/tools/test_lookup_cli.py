import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fakes.shopify import FakeTransport
from tool_support import POLICY, SECRET, SESSION, canary_for, email_for, shipped_order

from gisting.shopify.jsonvalue import JsonObject
from gisting.shopify.results import Uncertain
from gisting.tools.cli import Runtime, main

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GISTING_EMAIL_SECRET", SECRET)


@pytest.fixture
def empty_env_file(tmp_path: Path) -> Path:
    path = tmp_path / "empty.env"
    path.write_text("")
    return path


def feed(monkeypatch: pytest.MonkeyPatch, document: JsonObject | str) -> None:
    text = document if isinstance(document, str) else json.dumps(document)
    monkeypatch.setattr(sys, "stdin", io.StringIO(text))


def request(number: str, email: str, session: str = SESSION) -> JsonObject:
    return {"arguments": {"order_number": number, "email": email}, "session_id": session}


def run(args: list[str], env_file: Path, transport: FakeTransport | None = None) -> int:
    argv = ["call", "lookup_order", "--env-file", str(env_file), *args]
    return main(argv, Runtime(transport or FakeTransport([shipped_order(1042)]), lambda _s: None))


@pytest.mark.usefixtures("secret")
def test_match_writes_one_json_line_with_result_and_public_trace(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], empty_env_file: Path
) -> None:
    feed(monkeypatch, request("#1042", email_for(1042)))
    assert run([], empty_env_file) == 0
    captured = capsys.readouterr()
    lines = captured.out.splitlines()
    assert len(lines) == 1
    assert captured.out.endswith("\n")
    document = json.loads(lines[0])
    assert set(document) == {"result", "trace"}
    assert document["result"]["status"] == "found"
    assert document["trace"] == {
        "tool": "lookup_order",
        "order_number": "#1042",
        "outcome": "completed",
    }
    assert canary_for(1042) not in json.dumps(document["trace"])
    assert captured.err == ""


@pytest.mark.usefixtures("secret")
def test_internal_flag_adds_the_internal_projection(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], empty_env_file: Path
) -> None:
    feed(monkeypatch, request("#1042", "wrong@example.com"))
    assert run(["--internal"], empty_env_file) == 0
    document = json.loads(capsys.readouterr().out)
    assert set(document) == {"result", "trace", "internal"}
    assert document["internal"]["result_type"] == "Mismatch"
    assert "wrong@example.com" not in json.dumps(document)


@pytest.mark.usefixtures("secret")
def test_no_match_exits_zero_and_is_identical_for_unknown_orders(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], empty_env_file: Path
) -> None:
    feed(monkeypatch, request("#1042", "wrong@example.com"))
    assert run([], empty_env_file) == 0
    wrong_email = capsys.readouterr().out
    feed(monkeypatch, request("#1042", email_for(1042)))
    assert run([], empty_env_file, FakeTransport([])) == 0
    not_found = capsys.readouterr().out
    assert wrong_email == not_found
    assert json.loads(wrong_email)["result"]["status"] == "no_match"


@pytest.mark.usefixtures("secret")
def test_unavailable_exits_non_zero_and_logs_to_stderr(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], empty_env_file: Path
) -> None:
    fake = FakeTransport([shipped_order(1042)])
    for _ in range(3):
        fake.fail("order_state", Uncertain("timeout"))
    feed(monkeypatch, request("#1042", email_for(1042)))
    assert run([], empty_env_file, fake) == 1
    captured = capsys.readouterr()
    document = json.loads(captured.out)
    assert document["result"]["status"] == "unavailable"
    assert document["trace"]["outcome"] == "unavailable"
    assert len(captured.out.splitlines()) == 1
    assert "unavailable" in captured.err


@pytest.mark.usefixtures("secret")
@pytest.mark.parametrize(
    "stdin",
    [
        "not json",
        "[]",
        "{}",
        '{"arguments": {}}',
        '{"arguments": {}, "session_id": ""}',
        '{"arguments": [], "session_id": "s"}',
    ],
)
def test_bad_stdin_is_a_usage_error_with_empty_stdout(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    empty_env_file: Path,
    stdin: str,
) -> None:
    feed(monkeypatch, stdin)
    assert run([], empty_env_file) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "gisting.tools" in captured.err


def test_missing_secret_is_a_usage_error_with_empty_stdout(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], empty_env_file: Path
) -> None:
    monkeypatch.delenv("GISTING_EMAIL_SECRET", raising=False)
    feed(monkeypatch, request("#1042", email_for(1042)))
    assert run([], empty_env_file) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "GISTING_EMAIL_SECRET" in captured.err
    assert SECRET not in captured.err


def test_module_entry_point_reports_missing_secret_without_stdout(tmp_path: Path) -> None:
    empty = tmp_path / "empty.env"
    empty.write_text("")
    env = {key: value for key, value in os.environ.items() if key != "GISTING_EMAIL_SECRET"}
    completed = subprocess.run(
        [sys.executable, "-m", "gisting.tools", "call", "lookup_order", "--env-file", str(empty)],
        input=json.dumps(request("#1042", "a@b.c")),
        capture_output=True,
        text=True,
        env=env,
        cwd=REPO,
        check=False,
    )
    assert completed.returncode == 2
    assert completed.stdout == ""
    assert "GISTING_EMAIL_SECRET" in completed.stderr


def test_unknown_tool_is_rejected_by_the_parser(empty_env_file: Path) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["call", "refund_order", "--env-file", str(empty_env_file)])
    assert exit_info.value.code == 2


@pytest.mark.usefixtures("secret")
def test_deeply_nested_json_is_a_usage_error_without_traceback(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], empty_env_file: Path
) -> None:
    feed(monkeypatch, "[" * 200_000)
    assert run([], empty_env_file) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.count("\n") == 1
    assert "nested too deeply" in captured.err
    assert "Traceback" not in captured.err


def invoke(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    env_file: Path,
    transport: FakeTransport,
    call: tuple[str, str],
) -> tuple[int, str, str]:
    feed(monkeypatch, request(*call))
    code = run([], env_file, transport)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def readback_mismatch() -> FakeTransport:
    return FakeTransport([shipped_order(1042, email="someone@orders.example.com")])


def not_a_demo_order() -> FakeTransport:
    order = shipped_order(1042)
    order.test = False
    return FakeTransport([order])


IN_RANGE_NO_MATCH = {
    "input_email_mismatch": (lambda: FakeTransport([shipped_order(1042)]), "wrong@example.com"),
    "not_found": (lambda: FakeTransport([]), email_for(1042)),
    "not_demo_order": (not_a_demo_order, email_for(1042)),
    "readback_mismatch": (readback_mismatch, email_for(1042)),
}


@pytest.mark.usefixtures("secret")
def test_in_range_no_match_branches_have_identical_rc_stdout_and_stderr(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], empty_env_file: Path
) -> None:
    triples = {
        name: invoke(monkeypatch, capsys, empty_env_file, make(), ("#1042", email))
        for name, (make, email) in IN_RANGE_NO_MATCH.items()
    }
    assert len(set(triples.values())) == 1
    code, out, err = triples["not_found"]
    assert (code, err) == (0, "")
    assert json.loads(out)["result"]["status"] == "no_match"


@pytest.mark.usefixtures("secret")
@pytest.mark.parametrize(
    "spellings",
    [("#9999", "9999", " 09999 "), ("abc", "", "#", "١٠٤٢", "1042.0")],
    ids=["out_of_range", "malformed"],
)
def test_out_of_range_and_malformed_inputs_are_uniform_within_their_group(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    empty_env_file: Path,
    spellings: tuple[str, ...],
) -> None:
    triples = {
        invoke(monkeypatch, capsys, empty_env_file, FakeTransport([]), (number, "x@y.z"))
        for number in spellings
    }
    assert len(triples) == 1
    code, _out, err = next(iter(triples))
    assert (code, err) == (0, "")


@pytest.mark.usefixtures("secret")
def test_every_cli_call_starts_with_a_fresh_failure_count(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], empty_env_file: Path
) -> None:
    for _ in range(POLICY.failure_limit * 2):
        feed(monkeypatch, request("#1042", "wrong@example.com"))
        assert run(["--internal"], empty_env_file) == 0
        document = json.loads(capsys.readouterr().out)
        assert document["result"]["status"] == "no_match"
        assert document["internal"]["failures_before"] == 0
    feed(monkeypatch, request("#1042", email_for(1042)))
    assert run([], empty_env_file) == 0
    assert json.loads(capsys.readouterr().out)["result"]["status"] == "found"
