import json
from pathlib import Path
from typing import Any

import pytest
from fakes.agent_launch import inprocess_launcher
from fakes.tokenizer import synthetic_prompt_tokenizer

from gisting.eval.case_files import load_cases
from gisting.eval.replay import replay_problems
from gisting.eval.report import load_rows
from gisting.eval.runner import RunSpec, Selection, run_cases, select_cases

ROOT = Path(__file__).resolve().parents[2]
SECRET = "replay-test-secret-value"
LOADED, _PROBLEMS = load_cases(ROOT)
TOKENIZER = synthetic_prompt_tokenizer()


def rows_for(directory: Path, mode: str) -> list[dict[str, Any]]:
    env_file = directory / "empty.env"
    env_file.write_text("")
    mp = pytest.MonkeyPatch()
    mp.setenv("GISTING_EMAIL_SECRET", SECRET)
    try:
        cases = select_cases(LOADED, Selection(("dev",), per_red_line=2))
        spec = RunSpec(ROOT, mode, directory, inprocess_launcher(env_file), env_file=env_file)
        return [dict(row) for row in load_rows(run_cases(spec, cases).path)]
    finally:
        mp.undo()


@pytest.mark.parametrize("mode", ["full", "gist"])
def test_recorded_token_counts_replay_exactly_with_the_same_tokenizer(
    tmp_path: Path, mode: str
) -> None:
    rows = rows_for(tmp_path, mode)
    assert replay_problems(rows, TOKENIZER, mode) == []


def slot_free(row: dict[str, Any]) -> list[int]:
    call = row["internal"]["model_calls"][0]
    return [i for i, item in enumerate(call["input_messages"]) if "{email_" not in json.dumps(item)]


def test_some_messages_are_redacted_and_some_are_not(tmp_path: Path) -> None:
    rows = rows_for(tmp_path, "full")
    assert any(
        "{email_" in json.dumps(r["internal"]["model_calls"][0]["input_messages"]) for r in rows
    )
    assert any(slot_free(row) for row in rows)


def test_a_changed_message_count_without_an_email_is_reported(tmp_path: Path) -> None:
    rows = rows_for(tmp_path, "full")
    row = next(row for row in rows if slot_free(row))
    index = slot_free(row)[0]
    row["internal"]["model_calls"][0]["message_tokens"][index] += 1
    problems = replay_problems(rows, TOKENIZER, "full")
    assert any(f"message {index}: recorded" in p and row["case_id"] in p for p in problems)


def test_a_changed_part_of_the_prompt_stats_is_reported(tmp_path: Path) -> None:
    rows = rows_for(tmp_path, "full")
    rows[1]["internal"]["model_calls"][0]["tokens"]["history"] += 1
    problems = replay_problems(rows, TOKENIZER, "full")
    assert len(problems) == 1
    assert rows[1]["case_id"] in problems[0]
    assert "history is" in problems[0]
    rows[1]["internal"]["model_calls"][0]["tokens"]["total"] -= 1
    assert any("total is" in item for item in replay_problems(rows, TOKENIZER, "full"))


def test_a_cheaper_rules_count_is_reported(tmp_path: Path) -> None:
    rows = rows_for(tmp_path, "gist")
    rows[0]["internal"]["model_calls"][0]["tokens"]["rules"] = 1
    assert any("rules is 1" in item for item in replay_problems(rows, TOKENIZER, "gist"))


def test_an_edited_message_without_an_email_no_longer_matches(tmp_path: Path) -> None:
    rows = rows_for(tmp_path, "full")
    row = next(row for row in rows if slot_free(row))
    index = slot_free(row)[0]
    row["internal"]["model_calls"][0]["input_messages"][index]["content"] += " and many more words"
    assert any(f"message {index}" in item for item in replay_problems(rows, TOKENIZER, "full"))


def test_message_counts_that_do_not_line_up_are_reported(tmp_path: Path) -> None:
    rows = rows_for(tmp_path, "full")
    rows[0]["internal"]["model_calls"][0]["message_tokens"].append(5)
    assert any("line up" in item for item in replay_problems(rows, TOKENIZER, "full"))


def test_gist_mode_needs_the_gist_size_in_the_model_identity(tmp_path: Path) -> None:
    rows = rows_for(tmp_path, "gist")
    for row in rows:
        row["internal"]["model"] = {}
    problems = replay_problems(rows, TOKENIZER, "gist")
    assert problems
    assert "gist" in problems[0]


def test_error_rows_have_nothing_to_replay(tmp_path: Path) -> None:
    rows = rows_for(tmp_path, "full")
    rows[0] = {"case_id": rows[0]["case_id"], "mode": "full", "error": {"type": "x"}}
    assert replay_problems(rows, TOKENIZER, "full") == []
