import json
from pathlib import Path

import pytest
from conftest import SCRIPTS_DIR, Guard
from eval_repo import case_line, put, seed_plan, user_text_line

REPO = SCRIPTS_DIR.parent
SCRIPT = "check_eval_sets.py"
POLICY = "data/eval/contamination-v1.json"
TEMPLATES = "data/gist/templates.json"
TRAINING = {
    "first_call": {
        "families": {
            "where_is_it": {
                "split": "train",
                "templates": ["Where is my order {order}? My email is {email}."],
            }
        }
    }
}
FRESH = "Could you list everything that was bundled inside the box for the garden shed"
FRESH_TWO = "My neighbour keeps receiving deliveries addressed to me and I am quite upset"
DEV_FILE = "eval/cases/dev/box_contents.jsonl"
TRAIN_FILE = "eval/cases/train/neighbour.jsonl"


@pytest.fixture
def root(tmp_path: Path) -> Path:
    seed_plan(tmp_path)
    (tmp_path / "data/eval").mkdir(parents=True)
    (tmp_path / POLICY).write_text((REPO / POLICY).read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "data/gist").mkdir(parents=True)
    (tmp_path / TEMPLATES).write_text(json.dumps(TRAINING), encoding="utf-8")
    put(tmp_path, DEV_FILE, user_text_line(FRESH, id="box_one", family="box_contents"))
    put(
        tmp_path,
        TRAIN_FILE,
        user_text_line(FRESH_TWO, id="neighbour_one", split="train", family="neighbour"),
    )
    return tmp_path


def test_the_committed_skeleton_passes(guard: Guard) -> None:
    result = guard(SCRIPT, REPO)
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")


def test_distinct_families_and_texts_pass(root: Path, guard: Guard) -> None:
    result = guard(SCRIPT, root)
    assert (result.returncode, result.stderr) == (0, "")


def test_a_family_in_two_splits_fails(root: Path, guard: Guard) -> None:
    other = user_text_line(FRESH_TWO + " twice", id="box_two", split="train", family="box_contents")
    put(root, "eval/cases/train/box_contents.jsonl", other)
    result = guard(SCRIPT, root)
    assert result.returncode == 1
    assert "family box_contents is used in more than one split: dev, train" in result.stderr


def test_a_family_named_like_a_training_family_fails(root: Path, guard: Guard) -> None:
    line = user_text_line(
        "A broken kettle lid arrived this morning", id="kettle", family="where_is_it"
    )
    put(root, "eval/cases/dev/where_is_it.jsonl", line)
    result = guard(SCRIPT, root)
    assert result.returncode == 1
    assert "family where_is_it is also a training family" in result.stderr


def test_the_same_phrase_in_two_splits_fails(root: Path, guard: Guard) -> None:
    echoed = user_text_line(
        FRESH + " please", id="neighbour_one", split="train", family="neighbour"
    )
    put(root, TRAIN_FILE, echoed)
    result = guard(SCRIPT, root)
    assert result.returncode == 1
    assert f"{TRAIN_FILE}:1: neighbour_one shares 7 n-grams with box_one" in result.stderr


def test_a_training_template_with_concrete_values_filled_in_fails(root: Path, guard: Guard) -> None:
    body = "Where is my order #1042? My email is ava.chen@example.com."
    put(root, DEV_FILE, user_text_line(body, id="box_one", family="box_contents"))
    result = guard(SCRIPT, root)
    assert result.returncode == 1
    assert "box_one shares 2 n-grams with first_call.families.where_is_it.templates[0]" in (
        result.stderr
    )


def test_assistant_turns_are_not_scanned(root: Path, guard: Guard) -> None:
    echo = "Where is my order #1042? My email is ava.chen@example.com."
    history: list[dict[str, object]] = [
        {"role": "assistant", "content": echo, "tool_calls": []},
        {"role": "user", "content": FRESH, "tool_calls": []},
    ]
    put(root, DEV_FILE, case_line(id="box_one", family="box_contents", messages=history))
    assert guard(SCRIPT, root).returncode == 0


def test_a_missing_policy_or_templates_file_fails(root: Path, guard: Guard) -> None:
    kept = (root / POLICY).read_text(encoding="utf-8")
    (root / POLICY).unlink()
    result = guard(SCRIPT, root)
    assert result.returncode == 1
    assert POLICY in result.stderr
    (root / POLICY).write_text(kept, encoding="utf-8")
    (root / TEMPLATES).unlink()
    assert TEMPLATES in guard(SCRIPT, root).stderr


def test_a_case_copied_from_a_real_training_template_fails(root: Path, guard: Guard) -> None:
    (root / TEMPLATES).write_text((REPO / TEMPLATES).read_text(encoding="utf-8"), encoding="utf-8")
    body = "Where is my order #2093? My email is mia_santos.gmail@example.com."
    put(root, DEV_FILE, user_text_line(body, id="box_one", family="box_contents"))
    result = guard(SCRIPT, root)
    assert result.returncode == 1
    assert "box_one shares" in result.stderr
