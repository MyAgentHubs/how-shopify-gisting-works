import io
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from agent_support import EMAIL, RENDERED, SECRET, SESSION, demo_order, good_call, tool_call
from fakes.model import FakeModel
from fakes.shopify import FakeTransport
from fakes.tokenizer import synthetic_prompt_tokenizer

from gisting.agent import cli
from gisting.agent.cli import Loaded, Runtime, main
from gisting.model_server.config import ModelConfig
from gisting.shopify.jsonvalue import JsonObject
from gisting.tools.cli import Runtime as ToolsRuntime

ASK = "Which order do you mean?"


@pytest.fixture(autouse=True)
def secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GISTING_EMAIL_SECRET", SECRET)


@pytest.fixture
def empty_env_file(tmp_path: Path) -> Path:
    path = tmp_path / "empty.env"
    path.write_text("")
    return path


def line(session: str, content: str) -> str:
    request: JsonObject = {
        "session_id": session,
        "messages": [{"role": "user", "content": content}],
    }
    return json.dumps(request)


def run_batch(
    monkeypatch: pytest.MonkeyPatch,
    env_file: Path,
    stdin: str,
    *outputs: str,
    extra: tuple[str, ...] = (),
) -> int:
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))
    runtime = Runtime(
        ToolsRuntime(FakeTransport([demo_order()]), lambda _seconds: None),
        FakeModel(list(outputs)),
        synthetic_prompt_tokenizer(),
    )
    argv = ["run", "--batch", "--env-file", str(env_file), *extra]
    return main(argv, runtime)


def rows(capsys: pytest.CaptureFixture[str]) -> list[dict[str, Any]]:
    return [json.loads(text) for text in capsys.readouterr().out.splitlines()]


def test_one_result_line_per_request_line_in_order(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], empty_env_file: Path
) -> None:
    stdin = line("s1", f"Where is #1042? {EMAIL}") + "\n" + line("s2", "hello") + "\n"
    assert run_batch(monkeypatch, empty_env_file, stdin, good_call(), ASK) == 0
    first, second = rows(capsys)
    assert first["answer"] == RENDERED
    assert second["answer"] == ASK
    assert set(first) == {"answer", "trace"}


def test_the_internal_flag_adds_the_internal_projection_to_every_row(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], empty_env_file: Path
) -> None:
    stdin = line("s1", "hello") + "\n" + line("s2", "hello") + "\n"
    assert run_batch(monkeypatch, empty_env_file, stdin, ASK, ASK, extra=("--internal",)) == 0
    assert all(set(row) == {"answer", "trace", "internal"} for row in rows(capsys))


def test_a_bad_line_is_a_typed_error_row_and_the_rest_still_run(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], empty_env_file: Path
) -> None:
    stdin = "\n".join([
        line("s1", "hello"),
        "not json",
        '{"session_id": "s", "messages": []}',
        "",
        line("s2", "hello"),
    ])
    assert run_batch(monkeypatch, empty_env_file, stdin, ASK, ASK) == 1
    captured = capsys.readouterr()
    results = [json.loads(text) for text in captured.out.splitlines()]
    assert [("error" in row) for row in results] == [False, True, True, True, False]
    assert {row["error"]["type"] for row in results if "error" in row} == {"invalid_request"}
    assert results[0]["answer"] == results[4]["answer"] == ASK
    assert "Traceback" not in captured.err


def test_a_fallback_row_keeps_its_answer_and_makes_the_exit_non_zero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], empty_env_file: Path
) -> None:
    bad = tool_call(order_number="#1042")
    stdin = line("s1", f"Where is #1042? {EMAIL}") + "\n" + line("s2", "hello") + "\n"
    code = run_batch(monkeypatch, empty_env_file, stdin, bad, bad, ASK, extra=("--internal",))
    assert code == 1
    first, second = rows(capsys)
    assert first["internal"]["fallback_reason"] == "invalid_tool_call"
    assert second["answer"] == ASK


def test_the_model_is_loaded_once_for_the_whole_batch(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], empty_env_file: Path
) -> None:
    loads: list[str] = []
    model = FakeModel([ASK, ASK, ASK])

    def load(_config: ModelConfig, mode: str) -> Loaded:
        loads.append(mode)
        return Loaded(model, synthetic_prompt_tokenizer())

    monkeypatch.setattr(cli, "load_model", load)
    stdin = "".join(line(f"s{i}", "hello") + "\n" for i in range(3))
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))
    runtime = Runtime(ToolsRuntime(FakeTransport([demo_order()]), lambda _seconds: None))
    assert main(["run", "--batch", "--env-file", str(empty_env_file)], runtime) == 0
    assert loads == ["full"]
    assert len(rows(capsys)) == 3


def test_an_empty_batch_prints_nothing_and_succeeds(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], empty_env_file: Path
) -> None:
    assert run_batch(monkeypatch, empty_env_file, "") == 0
    assert capsys.readouterr().out == ""


def test_a_missing_secret_stops_the_batch_before_any_row(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], empty_env_file: Path
) -> None:
    monkeypatch.delenv("GISTING_EMAIL_SECRET")
    assert run_batch(monkeypatch, empty_env_file, line(SESSION, "hello") + "\n", ASK) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "GISTING_EMAIL_SECRET" in captured.err


def test_the_module_entry_point_reports_a_model_that_cannot_load_before_any_row(
    tmp_path: Path,
) -> None:
    empty = tmp_path / "empty.env"
    empty.write_text("")
    env = {
        **os.environ,
        "GISTING_EMAIL_SECRET": SECRET,
        "SHOPIFY_CLIENT_SECRET": "unused",
        "GISTING_MODEL_DIR": str(tmp_path / "no-model"),
    }
    completed = subprocess.run(
        [sys.executable, "-m", "gisting.agent", "run", "--batch", "--env-file", str(empty)],
        input=line(SESSION, "hello") + "\n",
        capture_output=True,
        text=True,
        env=env,
        cwd=Path(__file__).resolve().parents[2],
        check=False,
    )
    assert completed.returncode == 2
    assert completed.stdout == ""
    assert "cannot load the model" in completed.stderr
