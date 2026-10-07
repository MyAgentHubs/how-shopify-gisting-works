import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from gisting.shopify.cli import main
from gisting.shopify.demo_email import demo_email

SECRET = "demo-emails-cli-secret"


@pytest.fixture
def env_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.delenv("GISTING_EMAIL_SECRET", raising=False)
    path = tmp_path / "empty.env"
    path.write_text("")
    return path


def run(monkeypatch: pytest.MonkeyPatch, stdin: str, *extra: str) -> int:
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))
    return main(["demo-emails", *extra])


def test_each_order_line_gets_its_demo_email_in_order(
    env_file: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("GISTING_EMAIL_SECRET", SECRET)
    stdin = '{"order_number": "#1042"}\n\n{"order_number": "1003"}\n'
    assert run(monkeypatch, stdin, "--env-file", str(env_file)) == 0
    captured = capsys.readouterr()
    rows = [json.loads(line) for line in captured.out.splitlines()]
    assert rows == [
        {"order_number": "#1042", "email": demo_email(SECRET, "#1042")},
        {"order_number": "1003", "email": demo_email(SECRET, "1003")},
    ]
    assert captured.err == ""


def test_the_secret_is_read_from_the_env_file(
    tmp_path: Path,
    env_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "with-secret.env"
    path.write_text(f"GISTING_EMAIL_SECRET={SECRET}\n")
    monkeypatch.setenv("GISTING_EMAIL_SECRET", "placeholder")
    monkeypatch.delenv("GISTING_EMAIL_SECRET")
    assert run(monkeypatch, '{"order_number": "#1042"}\n', "--env-file", str(path)) == 0
    assert json.loads(capsys.readouterr().out)["email"] == demo_email(SECRET, "#1042")


def test_a_missing_secret_is_a_usage_error_that_names_only_the_variable(
    env_file: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(monkeypatch, '{"order_number": "#1042"}\n', "--env-file", str(env_file)) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "GISTING_EMAIL_SECRET is not set" in captured.err


def test_a_missing_env_file_is_a_usage_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(monkeypatch, "", "--env-file", str(tmp_path / "none")) == 2
    assert "env file not found" in capsys.readouterr().err


@pytest.mark.parametrize(
    "line", ["not json", "[]", '{"order_number": 1042}', '{"order_number": "abc"}', "{}"]
)
def test_a_bad_input_line_is_a_usage_error_and_prints_nothing(
    line: str,
    env_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("GISTING_EMAIL_SECRET", SECRET)
    stdin = f'{{"order_number": "#1042"}}\n{line}\n'
    assert run(monkeypatch, stdin, "--env-file", str(env_file)) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert SECRET not in captured.err
    assert "line 2" in captured.err


def test_the_module_runs_as_a_subprocess(env_file: Path) -> None:
    env = {**os.environ, "GISTING_EMAIL_SECRET": SECRET}
    done = subprocess.run(
        [sys.executable, "-m", "gisting.shopify", "demo-emails", "--env-file", str(env_file)],
        input='{"order_number": "#1042"}\n',
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert done.returncode == 0
    assert json.loads(done.stdout)["email"] == demo_email(SECRET, "#1042")
