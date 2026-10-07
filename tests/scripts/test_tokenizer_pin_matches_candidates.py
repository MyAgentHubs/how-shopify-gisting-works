import json
from pathlib import Path
from typing import cast

REPO = Path(__file__).resolve().parents[2]
PIN = REPO / "data" / "eval" / "tokenizer-pin.json"
CANDIDATES = REPO / "models" / "candidates.json"
MODEL_ID = "qwen3-1.7b"
FULL_SHA_LENGTH = 40
PINNED_FILES = {"tokenizer.json", "tokenizer_config.json"}


def pinned() -> dict[str, object]:
    document: dict[str, object] = json.loads(PIN.read_text("utf-8"))
    return document


def candidate() -> dict[str, object]:
    entries: list[dict[str, object]] = json.loads(CANDIDATES.read_text("utf-8"))
    matching = [entry for entry in entries if entry["id"] == MODEL_ID]
    assert len(matching) == 1
    return matching[0]


def test_the_tokenizer_pin_names_the_revision_the_model_candidate_downloads() -> None:
    assert pinned()["revision"] == candidate()["revision"]


def test_the_tokenizer_pin_names_the_repo_the_model_candidate_downloads() -> None:
    assert pinned()["repo"] == candidate()["repo"]


def test_the_pinned_revision_is_a_full_commit_sha() -> None:
    revision = pinned()["revision"]
    assert isinstance(revision, str)
    assert len(revision) == FULL_SHA_LENGTH


def test_the_tokenizer_pin_names_exactly_the_two_tokenizer_files() -> None:
    files = cast(dict[str, str], pinned()["files"])
    assert set(files) == PINNED_FILES
