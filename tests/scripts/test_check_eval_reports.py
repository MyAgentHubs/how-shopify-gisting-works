import importlib
import json
import shutil
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from conftest import SCRIPTS_DIR, Guard
from fakes.tokenizer import synthetic_prompt_tokenizer
from reports_support import (
    REPO,
    build_reports,
    copy_inputs,
    drop_rules_tokens,
    edit,
    tamper_first_row,
)
from reports_support import mode_dir as report_dir

from gisting.eval.report import RULES_VERSION_CHARS
from gisting.prompt.fingerprint import rules_sha256
from gisting.prompt.tokenizer import PromptTokenizer

SCRIPT = "check_eval_reports.py"
TREE = "a" * 40
TOKENIZER = synthetic_prompt_tokenizer()

sys.path.insert(0, str(SCRIPTS_DIR))
guard_module: Any = importlib.import_module("check_eval_reports")
Check = Callable[[Path, PromptTokenizer | None], tuple[list[Any], list[str]]]
check: Check = guard_module.check


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    copy_inputs(tmp_path)
    build_reports(tmp_path, TREE, ("full",), monkeypatch)
    return tmp_path


def reasons(root: Path, tokenizer: PromptTokenizer = TOKENIZER) -> list[str]:
    violations, _notes = check(root, tokenizer)
    return [item.reason for item in violations]


def mode_dir(root: Path) -> Path:
    return report_dir(root, TREE)


def test_the_committed_tree_has_no_reports_yet_and_passes(guard: Guard) -> None:
    result = guard(SCRIPT, REPO)
    assert (result.returncode, result.stdout) == (0, "")


def test_a_fresh_report_regrades_and_replays_cleanly(root: Path) -> None:
    violations, notes = check(root, TOKENIZER)
    assert violations == []
    assert notes == []


def test_without_a_tokenizer_the_replay_is_skipped_and_said_so(root: Path) -> None:
    violations, notes = check(root, None)
    assert violations == []
    assert len(notes) == 1
    assert "token replay skipped" in notes[0]


def test_an_edited_metric_in_the_report_is_caught(root: Path) -> None:
    def change(report: dict[str, Any]) -> None:
        report["metrics"]["fact_provenance_failures"]["layers"]["final"]["failures"] = 5

    edit(mode_dir(root) / "report.json", change)
    found = reasons(root)
    assert any("metrics.fact_provenance_failures.layers.final.failures" in item for item in found)


def test_an_edited_answer_in_the_transcripts_is_caught(root: Path) -> None:
    path = mode_dir(root) / "transcripts.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    first = json.loads(lines[0])
    first["answer"] = "It arrives next Friday, I promise."
    lines[0] = json.dumps(first, sort_keys=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert any("differs from report.json" in item for item in reasons(root))


def test_a_changed_prompt_token_count_is_caught_by_the_replay(root: Path) -> None:
    path = mode_dir(root) / "transcripts.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    first = json.loads(lines[0])
    first["internal"]["model_calls"][0]["tokens"]["rules"] -= 100
    lines[0] = json.dumps(first, sort_keys=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert any("token replay" in item and "rules is" in item for item in reasons(root))


def write_record(root: Path, ids: list[str]) -> None:
    text = json.dumps({"reason": "search_policy not in production tools", "case_ids": ids})
    (mode_dir(root) / "not_applicable.json").write_text(text, encoding="utf-8")


def test_a_hand_written_exclusion_that_the_report_does_not_state_is_caught(root: Path) -> None:
    write_record(root, ["ctl_kb_help_basics_001"])
    found = reasons(root)
    assert any("cases.not_applicable" in item for item in found), found


def test_an_exclusion_of_a_red_line_case_is_caught(root: Path) -> None:
    loaded = json.loads((mode_dir(root) / "report.json").read_text(encoding="utf-8"))
    assert loaded["cases"]["not_applicable"]["count"] == 0
    write_record(root, ["borrowed_address_001"])
    assert any("not applicable record" in item for item in reasons(root))


def test_a_report_from_before_the_exclusion_record_still_regrades(root: Path) -> None:
    (mode_dir(root) / "not_applicable.json").unlink()
    edit(mode_dir(root) / "report.json", lambda r: r["cases"].pop("not_applicable"))
    assert reasons(root) == []


def stale_label(root: Path) -> None:
    edit(mode_dir(root) / "report.json", lambda r: r["run"].update(rules_version="0" * 16))


def test_a_fresh_report_is_of_the_current_epoch(root: Path) -> None:
    run = json.loads((mode_dir(root) / "report.json").read_text(encoding="utf-8"))["run"]
    assert run["rules_version"] == rules_sha256()[:RULES_VERSION_CHARS]


def test_a_self_reported_stale_label_does_not_skip_the_replay(root: Path) -> None:
    stale_label(root)
    tamper_first_row(mode_dir(root), drop_rules_tokens)
    found = reasons(root)
    assert any("token replay" in item and "rules is" in item for item in found)
    assert not any("cross-epoch" in item for item in found)


def test_without_a_git_repository_nothing_is_skipped_and_nothing_is_said(root: Path) -> None:
    violations, notes = check(root, TOKENIZER)
    assert violations == []
    assert notes == []


def test_a_malformed_epoch_field_does_not_skip_the_replay(root: Path) -> None:
    edit(mode_dir(root) / "report.json", lambda r: r["run"].pop("rules_version"))
    tamper_first_row(mode_dir(root), drop_rules_tokens)
    assert any("token replay" in item and "rules is" in item for item in reasons(root))


def test_a_directory_named_for_another_tree_is_caught(root: Path) -> None:
    other = root / "eval" / "reports" / ("b" * 40)
    other.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(mode_dir(root).parent, other)
    assert any("code_tree_sha differs" in item for item in reasons(root))


def test_a_demo_email_in_a_transcript_is_caught(root: Path) -> None:
    path = mode_dir(root) / "transcripts.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"note": "abcdefghij@orders.example.com"}\n')
    assert any("looks like a secret or a demo email" in item for item in reasons(root))


def test_a_report_with_run_errors_must_not_be_kept(root: Path) -> None:
    edit(mode_dir(root) / "report.json", lambda r: r["cases"].update(complete=False))
    assert any("incomplete report" in item for item in reasons(root))


def test_missing_files_and_bad_names_are_caught(root: Path) -> None:
    (mode_dir(root) / "report.json").unlink()
    odd = root / "eval" / "reports" / "not-a-sha" / "other"
    odd.mkdir(parents=True)
    found = reasons(root)
    assert any("report.json is missing" in item for item in found)
    assert any("40-hex tree sha" in item for item in found)
    assert any("mode directory must be one of" in item for item in found)


def test_the_script_runs_end_to_end_and_skips_the_replay_without_a_tokenizer(
    root: Path, guard: Guard, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GISTING_MODEL_DIR", str(tmp_path / "no-model"))
    result = guard(SCRIPT, root)
    assert result.returncode == 0
    assert "token replay skipped" in result.stderr


def test_a_row_from_another_backend_is_caught(root: Path) -> None:
    tamper_first_row(mode_dir(root), lambda row: row["internal"].update(backend_id="elsewhere"))
    found = reasons(root)
    assert any("backend_id differs" in item and "'elsewhere'" in item for item in found), found


def test_a_row_from_another_mode_is_caught(root: Path) -> None:
    tamper_first_row(mode_dir(root), lambda row: row["internal"].update(mode="gist"))
    assert any("mode differs" in item for item in reasons(root))


def test_a_report_that_names_another_mode_than_its_directory_is_caught(root: Path) -> None:
    edit(mode_dir(root) / "report.json", lambda r: r["run"].update(mode="gist"))
    assert any("mode differs: report.json says 'gist'" in item for item in reasons(root))


def test_a_report_that_names_another_backend_than_its_rows_is_caught(root: Path) -> None:
    edit(mode_dir(root) / "report.json", lambda r: r["run"].update(backend_id="elsewhere"))
    assert any("backend_id differs" in item for item in reasons(root))
