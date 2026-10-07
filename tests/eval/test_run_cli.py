import json
from pathlib import Path

import pytest

from gisting.eval.cli import main

ROOT = Path(__file__).resolve().parents[2]
SECRET = "run-cli-secret-value"


@pytest.fixture
def env_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.delenv("GISTING_EMAIL_SECRET", raising=False)
    path = tmp_path / "empty.env"
    path.write_text("")
    return path


def test_a_missing_secret_is_a_usage_error(
    tmp_path: Path, env_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    argv = ["run", "--mode", "full", "--out", str(tmp_path), "--env-file", str(env_file)]
    assert main(argv) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "GISTING_EMAIL_SECRET" in captured.err
    assert not list(tmp_path.glob("*.jsonl"))


def test_a_missing_env_file_is_a_usage_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    argv = ["run", "--mode", "full", "--out", str(tmp_path), "--env-file", str(tmp_path / "none")]
    assert main(argv) == 2
    assert "env file not found" in capsys.readouterr().err


def test_an_empty_selection_is_a_usage_error(
    tmp_path: Path,
    env_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("GISTING_EMAIL_SECRET", SECRET)
    argv = ["run", "--mode", "full", "--out", str(tmp_path), "--env-file", str(env_file)]
    assert main([*argv, "--family", "no_such_family"]) == 2
    assert "no cases match" in capsys.readouterr().err


def test_build_cases_still_prints_jsonl_to_stdout(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["build-cases", "--red-line", "3"]) == 0
    first = capsys.readouterr().out.splitlines()[0]
    assert json.loads(first)["red_line"] == 3


def test_a_model_that_cannot_load_stops_the_run_with_a_usage_error(
    tmp_path: Path,
    env_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("GISTING_EMAIL_SECRET", SECRET)
    monkeypatch.setenv("GISTING_MODEL_DIR", str(tmp_path / "no-model"))
    out = tmp_path / "out"
    argv = ["run", "--mode", "full", "--out", str(out), "--env-file", str(env_file)]
    assert main([*argv, "--per-red-line", "1"]) == 2
    captured = capsys.readouterr()
    assert "cannot load the model" in captured.err
    assert SECRET not in captured.err
    assert not out.exists()
