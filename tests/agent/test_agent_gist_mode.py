import io
import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from agent_support import (
    EMAIL,
    QUESTION,
    RENDERED,
    SECRET,
    SESSION,
    demo_order,
    good_call,
    internal_of,
    public_of,
    rig,
)
from fakes.model import FakeModel
from fakes.shopify import FakeTransport
from fakes.tokenizer import synthetic_prompt_tokenizer

from gisting.agent.cli import Runtime, main
from gisting.agent.turn import run_turn
from gisting.prompt.assemble import gist_rules
from gisting.prompt.messages import UserMessage
from gisting.tools.cli import Runtime as ToolsRuntime

K = 16
ANSWER = "Your order #1042 is in transit."
TOKENIZER = synthetic_prompt_tokenizer()


@pytest.fixture(autouse=True)
def secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GISTING_EMAIL_SECRET", SECRET)
    monkeypatch.delenv("GISTING_GIST_DIR", raising=False)


@pytest.fixture
def empty_env_file(tmp_path: Path) -> Path:
    path = tmp_path / "empty.env"
    path.write_text("")
    return path


def feed(monkeypatch: pytest.MonkeyPatch) -> None:
    request = {"session_id": SESSION, "messages": [{"role": "user", "content": f"#1042 {EMAIL}"}]}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(request)))


def cli_run(mode: str, env_file: Path, model: FakeModel) -> int:
    tools = ToolsRuntime(FakeTransport([demo_order()]), lambda _seconds: None)
    runtime = Runtime(tools, model, TOKENIZER, K, "run-x")
    arguments = ["run", "--mode", mode, "--internal", "--env-file", str(env_file)]
    return main(arguments, runtime)


def test_gist_mode_sends_placeholders_for_the_rules_and_names_the_run(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], empty_env_file: Path
) -> None:
    feed(monkeypatch)
    model = FakeModel([good_call()])
    assert cli_run("gist", empty_env_file, model) == 0
    document = json.loads(capsys.readouterr().out)
    assert all(prompt.count(TOKENIZER.gist_placeholder) == K for prompt in model.prompts)
    assert document["internal"]["mode"] == "gist"
    assert document["internal"]["gist_run_id"] == "run-x"
    assert document["answer"] == RENDERED


def test_full_mode_is_the_default_and_never_uses_placeholders(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], empty_env_file: Path
) -> None:
    feed(monkeypatch)
    model = FakeModel([good_call()])
    assert cli_run("full", empty_env_file, model) == 0
    document = json.loads(capsys.readouterr().out)
    assert all(TOKENIZER.gist_placeholder not in prompt for prompt in model.prompts)
    assert document["internal"]["mode"] == "full"
    assert document["internal"]["gist_run_id"] is None


def test_the_rules_segment_shrinks_in_the_trace_and_nothing_else_does() -> None:
    full = rig(good_call(), ANSWER)
    gist = rig(good_call(), ANSWER)
    deps = replace(gist.deps, rules=gist_rules(TOKENIZER, K), mode="gist", gist_run_id="run-x")
    full_tokens = public_of(full.run())["tokens"]
    gist_tokens = public_of(run_turn(deps, SESSION, [UserMessage(QUESTION)]))["tokens"]
    assert gist_tokens["rules"] < full_tokens["rules"]
    assert gist_tokens["total"] < full_tokens["total"]
    for key in ("tools", "history", "tool_results"):
        assert gist_tokens[key] == full_tokens[key]


def test_gist_mode_without_an_artifact_directory_is_a_usage_error_naming_the_variable(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], empty_env_file: Path
) -> None:
    feed(monkeypatch)
    runtime = Runtime(ToolsRuntime(FakeTransport([demo_order()]), lambda _seconds: None))
    assert main(["run", "--mode", "gist", "--env-file", str(empty_env_file)], runtime) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "GISTING_GIST_DIR" in captured.err


def test_gist_mode_with_an_injected_model_but_no_artifact_count_is_refused(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], empty_env_file: Path
) -> None:
    feed(monkeypatch)
    tools = ToolsRuntime(FakeTransport([demo_order()]), lambda _seconds: None)
    runtime = Runtime(tools, FakeModel([]), TOKENIZER)
    assert main(["run", "--mode", "gist", "--env-file", str(empty_env_file)], runtime) == 2
    assert "loaded Gist artifact" in capsys.readouterr().err


def test_the_internal_trace_keys_include_mode_and_gist_run() -> None:
    internal = internal_of(rig(ANSWER).run())
    assert internal["mode"] == "full"
    assert "gist_run_id" in internal
