import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
from conftest import SCRIPTS_DIR, Guard, Populate
from fakes.real_model import MODEL_DIR, needs_tokenizer

from gisting.prompt.tokenizer import PromptTokenizer

REPO = SCRIPTS_DIR.parent
DATA = "prompts/qwen3_added_tokens.json"


@pytest.fixture
def check(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    monkeypatch.syspath_prepend(str(SCRIPTS_DIR))  # pyright: ignore[reportUnknownMemberType]
    spec = importlib.util.spec_from_file_location(
        "check_special_tokens", SCRIPTS_DIR / "check_special_tokens.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def encode_without_escaping(self: PromptTokenizer, text: str) -> list[int]:
    raw = self._tokenizer  # pyright: ignore[reportPrivateUsage]
    raw.encode_special_tokens = False
    return raw.encode(text, add_special_tokens=False).ids


def leak_unescaped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(PromptTokenizer, "encode_text", encode_without_escaping)


def test_the_committed_token_list_passes_against_the_project_tokenizer(guard: Guard) -> None:
    result = guard("check_special_tokens.py", REPO)
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")


def test_a_missing_token_list_fails(populate: Populate, guard: Guard) -> None:
    result = guard("check_special_tokens.py", populate({"README": "x"}))
    assert result.returncode == 1
    assert DATA in result.stderr


def test_a_corrupt_token_list_fails(populate: Populate, guard: Guard) -> None:
    result = guard("check_special_tokens.py", populate({DATA: '{"added_tokens": []}'}))
    assert result.returncode == 1
    assert DATA in result.stderr


def test_the_list_covers_every_qwen_control_token_the_prompt_layer_uses(
    check: ModuleType,
) -> None:
    entries = check.load_entries(REPO)
    contents = {entry.content for entry in entries}
    assert {"<|im_start|>", "<|im_end|>", "<tool_response>", "<think>", "</think>"} <= contents
    assert len(entries) == 26


def test_text_that_reaches_the_tokenizer_without_escaping_is_caught(
    check: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    leak_unescaped(monkeypatch)
    found = check.find_violations(REPO)
    assert found
    assert any("<tool_response>" in item.reason for item in found)


def test_a_failing_guard_exits_non_zero_when_escaping_is_missing(
    check: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    leak_unescaped(monkeypatch)
    assert check.main(["--root", str(REPO)]) == 1


@needs_tokenizer
def test_the_real_tokenizer_matches_the_list_and_escapes_every_token(check: ModuleType) -> None:
    assert check.find_real_violations(REPO, MODEL_DIR) == []


@needs_tokenizer
def test_the_real_tokenizer_fails_when_escaping_is_missing(
    check: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    leak_unescaped(monkeypatch)
    assert check.find_real_violations(REPO, MODEL_DIR)


@needs_tokenizer
def test_the_real_tokenizer_file_differing_from_the_list_is_a_violation(
    check: ModuleType, tmp_path: Path
) -> None:
    root = tmp_path / "root"
    (root / "prompts").mkdir(parents=True)
    text = (REPO / DATA).read_text(encoding="utf-8")
    (root / DATA).write_text(text.replace('"normalized": false', '"normalized": true', 1))
    found = check.find_real_violations(root, MODEL_DIR)
    assert any("differ" in item.reason for item in found)
