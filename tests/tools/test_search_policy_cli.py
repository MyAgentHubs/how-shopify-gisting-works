import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from policy_support import build

from gisting.shopify.jsonvalue import Json, JsonObject
from gisting.tools.cli import Runtime, main

REPO = Path(__file__).resolve().parents[2]


def feed(monkeypatch: pytest.MonkeyPatch, document: JsonObject | str) -> None:
    text = document if isinstance(document, str) else json.dumps(document)
    monkeypatch.setattr(sys, "stdin", io.StringIO(text))


def request(query: Json = "can I pay with paypal") -> JsonObject:
    return {"arguments": {"query": query}, "session_id": "session-1"}


def test_one_json_line_with_the_result_and_the_public_trace_and_no_secret_needed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("GISTING_EMAIL_SECRET", raising=False)
    feed(monkeypatch, request())
    assert main(["call", "search_policy"]) == 0
    captured = capsys.readouterr()
    assert len(captured.out.splitlines()) == 1
    document = json.loads(captured.out)
    assert set(document) == {"result", "trace"}
    assert document["result"]["status"] == "policy_found"
    assert document["trace"] == {
        "tool": "search_policy",
        "order_number": None,
        "outcome": "completed",
    }
    assert captured.err == ""


def test_internal_flag_adds_candidates_and_the_public_trace_never_carries_them(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    feed(monkeypatch, request())
    assert main(["call", "search_policy", "--internal"]) == 0
    document = json.loads(capsys.readouterr().out)
    assert set(document) == {"result", "trace", "internal"}
    assert "kb-pay-methods" in document["internal"]["detail"]
    assert "kb-pay-methods" not in json.dumps(document["trace"])


def test_no_match_is_success(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    feed(monkeypatch, request("what is the capital of France"))
    assert main(["call", "search_policy"]) == 0
    assert json.loads(capsys.readouterr().out)["result"] == {"status": "policy_no_match"}


@pytest.mark.parametrize(
    "document",
    [request(3), {"arguments": {}, "session_id": "s"}, {"arguments": {"query": "x"}}, "[1]", "{"],
    ids=["wrong_type", "missing_query", "missing_session", "not_object", "bad_json"],
)
def test_invalid_input_exits_two_with_one_stderr_line_and_no_stdout(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], document: JsonObject | str
) -> None:
    feed(monkeypatch, document)
    assert main(["call", "search_policy"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("gisting.tools: ") and captured.err.count("\n") == 1


def test_unreadable_data_exits_one_after_printing_the_unavailable_result(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    tool = build(tmp_path, {"kb-a": "apple"})
    (tmp_path / "entries.jsonl").write_text("not json\n")
    feed(monkeypatch, request("apple"))
    assert main(["call", "search_policy"], Runtime(search=tool)) == 1
    captured = capsys.readouterr()
    assert json.loads(captured.out)["result"] == {"status": "policy_unavailable"}
    assert captured.err.startswith("gisting.tools: search_policy unavailable: KbDataError")


def test_the_module_runs_as_a_process() -> None:
    env = {key: value for key, value in os.environ.items() if not key.startswith("GISTING_")}
    done = subprocess.run(
        [sys.executable, "-m", "gisting.tools", "call", "search_policy"],
        input=json.dumps(request()),
        capture_output=True,
        text=True,
        cwd=REPO,
        env=env,
        check=False,
    )
    assert done.returncode == 0
    assert json.loads(done.stdout)["result"]["status"] == "policy_found"
    assert done.stderr == ""
