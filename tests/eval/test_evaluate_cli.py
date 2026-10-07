import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest
from fakes.agent_launch import inprocess_launcher

from gisting.eval.cli import build_parser
from gisting.eval.cli_evaluate import handle_evaluate
from gisting.eval.runner import Launcher

SECRET = "evaluate-cli-secret-value"
GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.com",
    "HOME": "/nonexistent",
    "PATH": os.environ["PATH"],
}
REPO = Path(__file__).resolve().parents[2]
COPIED = ("eval/cases", "eval/metrics.toml", "data", "prompts")


def git(root: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, env=GIT_ENV, check=True
    )
    return done.stdout.strip()


@dataclass(frozen=True)
class Workspace:
    root: Path
    env_file: Path
    launch: Launcher

    def evaluate(self, *extra: str) -> int:
        argv = ["evaluate", "--root", str(self.root), "--env-file", str(self.env_file)]
        args = build_parser().parse_args([*argv, "--per-red-line", "2", *extra])
        return handle_evaluate(args, self.launch)


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Workspace:
    root = tmp_path / "repo"
    root.mkdir()
    for name in COPIED:
        source, target = REPO / name, root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, target)
        else:
            shutil.copyfile(source, target)
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "init")
    env_file = tmp_path / "empty.env"
    env_file.write_text("")
    monkeypatch.setenv("GISTING_EMAIL_SECRET", SECRET)
    monkeypatch.setenv("GISTING_GIST_DIR", str(tmp_path / "gist"))
    return Workspace(root, env_file, inprocess_launcher(env_file))


def test_a_dirty_tree_is_refused_before_anything_runs(
    workspace: Workspace, capsys: pytest.CaptureFixture[str]
) -> None:
    (workspace.root / "prompts" / "extra.txt").write_text("x")
    assert workspace.evaluate() == 2
    assert "uncommitted" in capsys.readouterr().err
    assert not (workspace.root / "eval" / "reports").exists()


def test_both_modes_run_and_land_under_the_code_tree_sha(
    workspace: Workspace, capsys: pytest.CaptureFixture[str]
) -> None:
    assert workspace.evaluate() == 0
    sha = git(workspace.root, "rev-parse", "HEAD^{tree}")
    for mode in ("full", "gist"):
        directory = workspace.root / "eval" / "reports" / sha / mode
        report = json.loads((directory / "report.json").read_text(encoding="utf-8"))
        assert report["run"]["code_tree_sha"] == sha
        assert report["run"]["mode"] == mode
        assert (directory / "transcripts.jsonl").is_file()
    out = capsys.readouterr().out
    assert "full: fact_provenance_failures" in out
    assert "gist: fact_provenance_failures" in out


def test_committed_reports_do_not_make_the_tree_dirty_or_change_the_key(
    workspace: Workspace,
) -> None:
    assert workspace.evaluate("--mode", "full") == 0
    sha = git(workspace.root, "rev-parse", "HEAD^{tree}")
    git(workspace.root, "add", "-A")
    git(workspace.root, "commit", "-q", "-m", "report")
    assert workspace.evaluate("--mode", "gist") == 0
    assert (workspace.root / "eval" / "reports" / sha / "gist" / "report.json").is_file()


def test_an_existing_report_is_never_overwritten(
    workspace: Workspace, capsys: pytest.CaptureFixture[str]
) -> None:
    assert workspace.evaluate("--mode", "full") == 0
    capsys.readouterr()
    assert workspace.evaluate("--mode", "full") == 2
    assert "already exists" in capsys.readouterr().err


def test_gist_mode_without_an_artifact_directory_stops_before_any_run(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("GISTING_GIST_DIR")
    assert workspace.evaluate() == 2
    assert "GISTING_GIST_DIR" in capsys.readouterr().err
    assert not (workspace.root / "eval" / "reports").exists()


def test_a_full_only_run_needs_no_gist_directory(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GISTING_GIST_DIR")
    assert workspace.evaluate("--mode", "full") == 0
