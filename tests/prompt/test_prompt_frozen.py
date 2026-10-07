import hashlib
import json
from pathlib import Path

from fakes.real_model import MODEL_DIR, needs_tokenizer

from gisting.prompt.files import PROMPTS_DIR, TOOLS_DIR
from gisting.prompt.fingerprint import rules_sha256, tools_sha256
from gisting.prompt.rules import rules_text
from gisting.prompt.tokenizer import PromptTokenizer

REGISTRY = Path(__file__).resolve().parents[2] / "data" / "freeze" / "frozen-prompts-v2.json"
FROZEN = json.loads(REGISTRY.read_text(encoding="utf-8"))
PHRASES_FILE = PROMPTS_DIR / "reply_phrases.json"
TOOLS_SEGMENT_FILES = {
    "qwen3_tools_preamble.txt",
    "qwen3_tools_postamble.txt",
    "chat_variants.json",
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def frozen_failure(what: str) -> str:
    return (
        f"{what} changed. Rules, tool definitions and reply phrases are frozen until the M3 "
        f"launch; changing them means retraining the Gist. See {FROZEN['decision']}."
    )


def test_the_decision_that_explains_the_freeze_exists() -> None:
    assert (REGISTRY.parents[2] / FROZEN["decision"]).is_file()


def test_the_rendered_rules_are_the_frozen_text() -> None:
    assert rules_sha256() == FROZEN["rules_sha256"], frozen_failure("the rendered rules")


def test_the_reply_phrases_are_the_frozen_file() -> None:
    assert digest(PHRASES_FILE) == FROZEN["reply_phrases_sha256"], frozen_failure("reply_phrases")


def test_the_tool_schema_files_are_exactly_the_frozen_set() -> None:
    present = {path.name: digest(path) for path in TOOLS_DIR.glob("*.json")}
    assert present == FROZEN["tool_files_sha256"], frozen_failure("the tool schema files")


def test_the_tool_preamble_postamble_and_chat_variants_are_the_frozen_files() -> None:
    present = {name: digest(PROMPTS_DIR / name) for name in FROZEN["tools_segment_files_sha256"]}
    assert present == FROZEN["tools_segment_files_sha256"], frozen_failure(
        "the tool preamble, postamble or chat variants"
    )
    assert set(present) == TOOLS_SEGMENT_FILES


@needs_tokenizer
def test_the_rendered_tools_segment_is_the_one_the_launch_gist_was_trained_on() -> None:
    tokenizer = PromptTokenizer.from_dir(MODEL_DIR)
    assert tools_sha256(tokenizer) == FROZEN["artifact"]["tools_sha256"], frozen_failure(
        "the tokenized tools segment"
    )


def test_the_frozen_rules_are_the_ones_the_launch_gist_was_trained_on() -> None:
    assert FROZEN["artifact"]["rules_sha256"] == FROZEN["rules_sha256"]


def test_the_rules_do_not_mention_search_policy() -> None:
    assert "search_policy" not in rules_text()
