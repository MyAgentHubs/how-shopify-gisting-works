import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from gisting.shopify.jsonvalue import Json, JsonObject
from gisting.tools.cli import main

REPO = Path(__file__).resolve().parents[2]


def feed(monkeypatch: pytest.MonkeyPatch, document: JsonObject | str) -> None:
    text = document if isinstance(document, str) else json.dumps(document)
    monkeypatch.setattr(sys, "stdin", io.StringIO(text))


def request(reason: Json = "customer_request", session: str = "session-1") -> JsonObject:
    return {"arguments": {"reason": reason}, "session_id": session}


def test_one_json_line_with_the_result_and_the_public_trace(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("GISTING_EMAIL_SECRET", raising=False)
    feed(monkeypatch, request())
    assert main(["call", "handoff_to_human"]) == 0
    captured = capsys.readouterr()
    assert len(captured.out.splitlines()) == 1
    document = json.loads(captured.out)
    assert set(document) == {"result", "trace"}
    assert document["result"]["status"] == "handed_off"
    assert document["result"]["ticket"].startswith("HO-")
    assert document["trace"] == {
        "tool": "handoff_to_human",
        "order_number": None,
        "outcome": "completed",
    }
    assert captured.err == ""


def test_the_same_session_always_gets_the_same_ticket(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    tickets: list[str] = []
    for session in ("s-1", "s-1", "s-2"):
        feed(monkeypatch, request(session=session))
        assert main(["call", "handoff_to_human"]) == 0
        tickets.append(json.loads(capsys.readouterr().out)["result"]["ticket"])
    assert tickets[0] == tickets[1]
    assert tickets[0] != tickets[2]


def test_internal_flag_adds_the_internal_projection(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    feed(monkeypatch, request("delayed"))
    assert main(["call", "handoff_to_human", "--internal"]) == 0
    document = json.loads(capsys.readouterr().out)
    assert set(document) == {"result", "trace", "internal"}
    assert document["internal"]["detail"] == "delayed"
    assert "delayed" not in json.dumps(document["trace"])


@pytest.mark.parametrize(
    "document",
    [request("angry"), request(3), {"arguments": {}, "session_id": "s"}, {"arguments": {}}],
    ids=["unknown_reason", "wrong_type", "missing_reason", "missing_session"],
)
def test_arguments_that_break_the_schema_exit_two_with_a_stderr_line(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], document: JsonObject
) -> None:
    feed(monkeypatch, document)
    assert main(["call", "handoff_to_human"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("gisting.tools: ")


def test_the_module_runs_as_a_process_without_any_secret_or_network_setting() -> None:
    env = {key: value for key, value in os.environ.items() if not key.startswith("GISTING_")}
    done = subprocess.run(
        [sys.executable, "-m", "gisting.tools", "call", "handoff_to_human"],
        input=json.dumps(request()),
        capture_output=True,
        text=True,
        cwd=REPO,
        env=env,
        check=False,
    )
    assert done.returncode == 0
    assert json.loads(done.stdout)["result"]["status"] == "handed_off"
    assert done.stderr == ""


def test_the_reminder_tool_runs_through_the_same_cli_contract(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("GISTING_EMAIL_SECRET", raising=False)
    feed(monkeypatch, {"arguments": {"order_number": "#1042"}, "session_id": "session-1"})
    assert main(["call", "send_shipping_reminder", "--internal"]) == 0
    captured = capsys.readouterr()
    document = json.loads(captured.out)
    assert set(document) == {"result", "trace", "internal"}
    assert document["result"]["status"] == "requested"
    assert document["result"]["reference"].startswith("SR-")
    assert document["trace"] == {
        "tool": "send_shipping_reminder",
        "order_number": None,
        "outcome": "completed",
    }
    assert document["internal"]["order_number"] == "#1042"
    assert captured.err == ""


def test_the_reminder_tool_rejects_a_missing_order_number_with_exit_two(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    feed(monkeypatch, {"arguments": {}, "session_id": "session-1"})
    assert main(["call", "send_shipping_reminder"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("gisting.tools: ")
