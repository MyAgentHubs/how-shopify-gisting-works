import json
import shutil
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pytest
from conftest import SCRIPTS_DIR
from fakes.agent_launch import inprocess_launcher

from gisting.eval.case_files import load_cases
from gisting.eval.cli_grade import grade_directory
from gisting.eval.runner import RunSpec, Selection, run_cases, select_cases

REPO = SCRIPTS_DIR.parent
SECRET = "reports-guard-secret-value"
COPIED = ("eval/cases", "eval/metrics.toml", "data/demo-orders", "prompts/agent_policy.json")


def copy_inputs(root: Path) -> None:
    for name in COPIED:
        source, target = REPO / name, root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, target, dirs_exist_ok=True)
        else:
            shutil.copyfile(source, target)


def mode_dir(root: Path, tree: str, mode: str = "full") -> Path:
    return root / "eval" / "reports" / tree / mode


def build_reports(
    root: Path, tree: str, modes: Sequence[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GISTING_EMAIL_SECRET", SECRET)
    env_file = root / "empty.env"
    env_file.write_text("")
    loaded, _ = load_cases(root)
    cases = select_cases(loaded, Selection(("dev",), per_red_line=2))
    for mode in modes:
        out = mode_dir(root, tree, mode)
        spec = RunSpec(root, mode, out, inprocess_launcher(env_file), env_file=env_file)
        run_cases(spec, cases)
        grade_directory(out, root, tree)


def edit(path: Path, change: Callable[[dict[str, Any]], None]) -> None:
    document = json.loads(path.read_text(encoding="utf-8"))
    change(document)
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def tamper_first_row(directory: Path, change: Callable[[dict[str, Any]], None]) -> None:
    path = directory / "transcripts.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    first = json.loads(lines[0])
    change(first)
    lines[0] = json.dumps(first, sort_keys=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def drop_rules_tokens(row: dict[str, Any]) -> None:
    row["internal"]["model_calls"][0]["tokens"]["rules"] -= 100
