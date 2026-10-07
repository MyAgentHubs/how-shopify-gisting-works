import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from agent_support import (
    CANARY,
    EMAIL,
    NUMBER,
    RENDERED,
    SECRET,
    SESSION,
    demo_order,
    good_call,
    tool_call,
)
from fakes.model import FakeModel
from fakes.shopify import FakeTransport
from fakes.tokenizer import synthetic_prompt_tokenizer

from gisting.agent.cli import Runtime, main
from gisting.prompt.phrases import load_phrases
from gisting.shopify.jsonvalue import JsonObject
from gisting.tools.cli import Runtime as ToolsRuntime
from gisting.tools.policy import LookupPolicy, PolicyError

REPO = Path(__file__).resolve().parents[2]
ANSWER = "Your order #1042 is in transit with Test Parcel."


@pytest.fixture(autouse=True)
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


def request(*contents: str) -> JsonObject:
    messages: list[JsonObject] = [{"role": "user", "content": content} for content in contents]
    return {"session_id": SESSION, "messages": [*messages]}


def run(args: list[str], env_file: Path, *outputs: str) -> int:
    runtime = Runtime(
        ToolsRuntime(FakeTransport([demo_order()]), lambda _seconds: None),
        FakeModel(list(outputs)),
        synthetic_prompt_tokenizer(),
    )
    return main(["run", "--env-file", str(env_file), *args], runtime)


def test_one_json_line_with_answer_and_public_trace(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], empty_env_file: Path
) -> None:
    feed(monkeypatch, request(f"Where is #1042? {EMAIL}"))
    assert run([], empty_env_file, good_call()) == 0
    captured = capsys.readouterr()
    assert len(captured.out.splitlines()) == 1
    assert captured.out.endswith("\n")
    document = json.loads(captured.out)
    assert set(document) == {"answer", "trace"}
    assert document["answer"] == RENDERED
    assert set(document["trace"]) == {"tools", "knowledge", "tokens", "latency"}
    assert document["trace"]["tools"][0]["order_number"] == "#1042"
    assert captured.err == ""


def test_internal_flag_adds_the_internal_projection_without_secrets(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], empty_env_file: Path
) -> None:
    feed(monkeypatch, request(f"Where is #1042? {EMAIL}"))
    assert run(["--internal"], empty_env_file, good_call()) == 0
    out = capsys.readouterr().out
    document = json.loads(out)
    assert set(document) == {"answer", "trace", "internal"}
    assert document["internal"]["model_calls"][0]["raw_output"] == good_call()
    assert SECRET not in out
    assert CANARY not in json.dumps(document["trace"])


def test_multi_turn_history_is_accepted(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], empty_env_file: Path
) -> None:
    messages: list[JsonObject] = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "Hello"},
        {"role": "user", "content": "thanks"},
    ]
    feed(monkeypatch, {"session_id": SESSION, "messages": [*messages]})
    assert run([], empty_env_file, "You are welcome.") == 0
    assert json.loads(capsys.readouterr().out)["answer"] == "You are welcome."


def handoff_request(last: str) -> JsonObject:
    messages: list[JsonObject] = [
        {"role": "user", "content": f"Where is #1042? {EMAIL}"},
        {"role": "assistant", "content": f"Sorry about that. {load_phrases().handoff_offer}"},
        {"role": "user", "content": last},
    ]
    return {"session_id": SESSION, "messages": [*messages]}


def test_a_yes_to_the_handoff_offer_runs_the_mock_handoff_tool(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], empty_env_file: Path
) -> None:
    feed(monkeypatch, handoff_request("yes please"))
    call = tool_call("handoff_to_human")
    assert run(["--internal"], empty_env_file, call) == 0
    document = json.loads(capsys.readouterr().out)
    assert document["answer"].startswith("Done. I have passed your request to our team.")
    assert document["trace"]["tools"] == [
        {"tool": "handoff_to_human", "order_number": None, "outcome": "completed"}
    ]
    assert document["internal"]["tool_calls"][0]["trace"]["detail"] == "customer_request"


def test_a_handoff_call_without_the_customer_agreeing_gets_the_offer_instead(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], empty_env_file: Path
) -> None:
    feed(monkeypatch, handoff_request("what carrier is it?"))
    call = tool_call("handoff_to_human")
    assert run([], empty_env_file, call) == 0
    document = json.loads(capsys.readouterr().out)
    assert document["answer"] == load_phrases().handoff_offer
    assert document["trace"]["tools"] == []


def test_fallback_still_prints_the_answer_but_exits_non_zero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], empty_env_file: Path
) -> None:
    bad = tool_call(order_number="#1042")
    feed(monkeypatch, request(f"Where is #1042? {EMAIL}"))
    assert run(["--internal"], empty_env_file, bad, bad) == 1
    captured = capsys.readouterr()
    document = json.loads(captured.out)
    assert document["internal"]["fallback_reason"] == "invalid_tool_call"
    assert len(captured.out.splitlines()) == 1
    assert "fallback: invalid_tool_call" in captured.err


@pytest.mark.parametrize(
    "stdin",
    [
        "not json",
        "[]",
        "{}",
        '{"messages": [{"role": "user", "content": "x"}]}',
        '{"session_id": "", "messages": [{"role": "user", "content": "x"}]}',
        '{"session_id": "s", "messages": []}',
        '{"session_id": "s", "messages": "hi"}',
        '{"session_id": "s", "messages": [{"role": "system", "content": "x"}]}',
        '{"session_id": "s", "messages": [{"role": "tool", "content": "x"}]}',
        '{"session_id": "s", "messages": [{"role": "user"}]}',
        '{"session_id": "s", "messages": ["x"]}',
        '{"session_id": "s", "messages": [{"role": "assistant", "content": "x"}]}',
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
    assert "gisting.agent" in captured.err


def test_missing_secret_is_a_usage_error_with_empty_stdout(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], empty_env_file: Path
) -> None:
    monkeypatch.delenv("GISTING_EMAIL_SECRET")
    feed(monkeypatch, request(f"Where is #1042? {EMAIL}"))
    assert run([], empty_env_file) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "GISTING_EMAIL_SECRET" in captured.err


def test_module_entry_point_reports_a_model_that_cannot_load(tmp_path: Path) -> None:
    empty = tmp_path / "empty.env"
    empty.write_text("")
    env = {
        **os.environ,
        "GISTING_EMAIL_SECRET": SECRET,
        "SHOPIFY_CLIENT_SECRET": "unused",
        "GISTING_MODEL_DIR": str(tmp_path / "no-model"),
    }
    completed = subprocess.run(
        [sys.executable, "-m", "gisting.agent", "run", "--env-file", str(empty)],
        input=json.dumps(request(f"order #{NUMBER}")),
        capture_output=True,
        text=True,
        env=env,
        cwd=REPO,
        check=False,
    )
    assert completed.returncode == 2
    assert completed.stdout == ""
    assert "cannot load the model" in completed.stderr
    assert SECRET not in completed.stderr


def test_deeply_nested_json_is_a_usage_error_without_traceback(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], empty_env_file: Path
) -> None:
    feed(monkeypatch, "[" * 200_000)
    assert run([], empty_env_file) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.count("\n") == 1
    assert "Traceback" not in captured.err


def test_a_broken_lookup_policy_file_is_a_usage_error_not_a_crash(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], empty_env_file: Path
) -> None:
    def broken() -> LookupPolicy:
        message = "unreadable"
        raise PolicyError(message)

    monkeypatch.setattr("gisting.agent.cli.load_policy", broken)
    feed(monkeypatch, request(f"Where is #1042? {EMAIL}"))
    assert run([], empty_env_file, good_call()) == 2
    assert "PolicyError" in capsys.readouterr().err
