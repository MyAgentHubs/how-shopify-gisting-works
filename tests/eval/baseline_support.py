import hashlib
import json
import os
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fakes.agent_launch import inprocess_launcher

from gisting.eval.case_files import load_cases
from gisting.eval.cli import main
from gisting.eval.cli_grade import grade_directory
from gisting.eval.runner import RunSpec, Selection, run_cases, select_cases

REPO = Path(__file__).resolve().parents[2]
SECRET = "baseline-cli-secret-value"
GOOD, BAD, ONE_BAD = "a" * 40, "b" * 40, "c" * 40
COPIED = ("eval/cases", "eval/metrics.toml", "data", "prompts")
EMPTY_BASELINE = '{"version": 1, "epochs": []}\n'
GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.com",
    "HOME": "/nonexistent",
    "PATH": os.environ["PATH"],
}
DEV_QUOTA = Selection(("dev",), per_red_line=8)
INVENTED = "Good news, it arrives next Friday."


def git(root: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, env=GIT_ENV, check=True
    )
    return done.stdout.strip()


def make_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for name in COPIED:
        source, target = REPO / name, tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, target)
        else:
            shutil.copyfile(source, target)
    (tmp_path / "eval" / "baseline.json").write_text(EMPTY_BASELINE, encoding="utf-8")
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "init")
    monkeypatch.setenv("GISTING_EMAIL_SECRET", SECRET)
    return tmp_path


def make_run(
    root: Path, sha: str, spoil: int = 0, mode: str = "full", selection: Selection = DEV_QUOTA
) -> Path:
    env_file = root.parent / "empty.env"
    env_file.write_text("")
    loaded, _ = load_cases(root)
    cases = select_cases(loaded, selection)
    out = root / "eval" / "reports" / sha / mode
    run_cases(RunSpec(root, mode, out, inprocess_launcher(env_file), env_file=env_file), cases)
    path = out / "transcripts.jsonl"
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    cases_by_id = {item.case.id: item.case for item in loaded}
    facts = [row for row in lines if cases_by_id[row["case_id"]].red_line == 1][:spoil]
    for row in facts:
        row["answer"] = INVENTED
    path.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in lines), encoding="utf-8")
    grade_directory(out, root, sha)
    return out


def changed(root: Path) -> str:
    return git(root, "status", "--porcelain", "--", ".", ":!eval/reports")


def baseline(root: Path) -> dict[str, Any]:
    return json.loads((root / "eval" / "baseline.json").read_text(encoding="utf-8"))


def update(root: Path, *extra: str) -> int:
    return main(["baseline-update", "--root", str(root), *extra])


def commit_baseline(root: Path) -> None:
    git(root, "add", "eval/baseline.json")
    git(root, "commit", "-q", "-m", "baseline")


def rewrite_rows(directory: Path, change: Callable[[list[dict[str, Any]]], object]) -> None:
    path = directory / "transcripts.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    change(rows)
    text = "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)
    path.write_text(text, encoding="utf-8")
    report = json.loads((directory / "report.json").read_text(encoding="utf-8"))
    report["cases"]["transcripts_sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
    (directory / "report.json").write_text(json.dumps(report), encoding="utf-8")


def refused_with(
    root: Path, capsys: pytest.CaptureFixture[str], directory: Path, word: str
) -> None:
    assert update(root, "--after", str(directory)) == 2
    assert word in capsys.readouterr().err
    assert baseline(root)["epochs"] == []
