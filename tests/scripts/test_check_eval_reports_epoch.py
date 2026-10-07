import importlib
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from conftest import SCRIPTS_DIR
from eval_repo import commit, git, init_repo, put
from fakes.tokenizer import synthetic_prompt_tokenizer
from reports_support import (
    build_reports,
    copy_inputs,
    drop_rules_tokens,
    edit,
    mode_dir,
    tamper_first_row,
)

from gisting.prompt.tokenizer import PromptTokenizer

MODES = ("full", "gist")
TOKENIZER = synthetic_prompt_tokenizer()
SKIPPED = "token replay skipped (cross-epoch)"

sys.path.insert(0, str(SCRIPTS_DIR))
guard_module: Any = importlib.import_module("check_eval_reports")
Check = Callable[[Path, PromptTokenizer | None], tuple[list[Any], list[str]]]
check: Check = guard_module.check


def seed_epoch_files(root: Path) -> None:
    put(root, "prompts/system_rules.md", "rules one")
    put(root, "prompts/tools/lookup_order.json", "{}")


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, str]:
    init_repo(tmp_path)
    copy_inputs(tmp_path)
    seed_epoch_files(tmp_path)
    commit(tmp_path, "code")
    tree = git(tmp_path, "rev-parse", "HEAD^{tree}")
    build_reports(tmp_path, tree, MODES, monkeypatch)
    return tmp_path, tree


def change_and_commit(root: Path, relative: str, text: str) -> None:
    put(root, relative, text)
    commit(root, f"change {relative}")


def token_problems(root: Path) -> tuple[list[str], list[str]]:
    violations, notes = check(root, TOKENIZER)
    return [item.reason for item in violations if "token replay" in item.reason], notes


def tamper_both(root: Path, tree: str) -> None:
    for mode in MODES:
        tamper_first_row(mode_dir(root, tree, mode), drop_rules_tokens)


def forget_hashes(directory: Path) -> None:
    path = directory / "transcripts.jsonl"
    rows: list[dict[str, Any]] = [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
    ]
    for row in rows:
        gist: dict[str, Any] | None = row["internal"]["model"].get("gist")
        if gist is not None:
            gist.update(rules_sha256="", tools_sha256="not-a-hash")
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8"
    )


def test_an_untouched_repository_replays_both_modes_cleanly(repo: tuple[Path, str]) -> None:
    root, _tree = repo
    assert token_problems(root) == ([], [])


def test_whatever_the_reports_say_about_their_epoch_the_current_one_is_replayed(
    repo: tuple[Path, str],
) -> None:
    root, tree = repo
    for mode in MODES:
        edit(
            mode_dir(root, tree, mode) / "report.json", lambda r: r["run"].update(rules_version="")
        )
    forget_hashes(mode_dir(root, tree, "gist"))
    tamper_both(root, tree)
    problems, notes = token_problems(root)
    assert len(problems) == 2
    assert not any(SKIPPED in note for note in notes)


def test_a_change_outside_the_epoch_paths_still_replays(repo: tuple[Path, str]) -> None:
    root, tree = repo
    change_and_commit(root, "prompts/agent_policy.json", "{}")
    tamper_both(root, tree)
    problems, notes = token_problems(root)
    assert len(problems) == 2
    assert notes == []


def test_a_changed_epoch_path_skips_both_modes_and_regrading_still_runs(
    repo: tuple[Path, str],
) -> None:
    root, tree = repo
    change_and_commit(root, "prompts/system_rules.md", "rules two")
    tamper_both(root, tree)
    tamper_first_row(mode_dir(root, tree), lambda row: row.update(answer="It arrives next Friday."))
    violations, notes = check(root, TOKENIZER)
    assert [item for item in violations if "token replay" in item.reason] == []
    assert any("differs from report.json" in item.reason for item in violations)
    assert sum(note.startswith(SKIPPED) for note in notes) == 3
    assert any("2 of 2 reports" in note for note in notes)


def test_a_tools_only_change_skips_full_and_gist_alike(repo: tuple[Path, str]) -> None:
    root, tree = repo
    change_and_commit(root, "prompts/tools/lookup_order.json", '{"changed": true}')
    tamper_both(root, tree)
    problems, notes = token_problems(root)
    assert problems == []
    assert sum(" for eval/reports/" in note and "/full" in note for note in notes) == 1
    assert sum(" for eval/reports/" in note and "/gist" in note for note in notes) == 1


def test_the_reports_own_label_is_shown_but_does_not_decide(repo: tuple[Path, str]) -> None:
    root, tree = repo
    change_and_commit(root, "prompts/system_rules.md", "rules two")
    edit(mode_dir(root, tree) / "report.json", lambda r: r["run"].update(rules_version="f" * 16))
    _problems, notes = token_problems(root)
    assert any("reported rules_version " + "f" * 16 in note for note in notes)


def test_a_tree_missing_from_the_repository_is_replayed_even_when_the_inputs_changed(
    repo: tuple[Path, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _tree = repo
    change_and_commit(root, "prompts/system_rules.md", "rules two")
    ghost = "c" * 40
    build_reports(root, ghost, MODES, monkeypatch)
    tamper_both(root, ghost)
    violations, notes = check(root, TOKENIZER)
    replayed = [item for item in violations if ghost in item.path and "token replay" in item.reason]
    assert len(replayed) == 2
    assert not any(ghost in note and SKIPPED in note for note in notes)


def test_without_a_usable_git_the_replay_is_never_skipped(
    repo: tuple[Path, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, tree = repo
    change_and_commit(root, "prompts/system_rules.md", "rules two")
    tamper_both(root, tree)
    monkeypatch.setenv("PATH", str(root / "nowhere"))
    problems, notes = token_problems(root)
    assert len(problems) == 2
    assert not any(SKIPPED in note for note in notes)
