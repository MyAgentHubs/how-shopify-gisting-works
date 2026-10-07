import hashlib
import json
from pathlib import Path

import pytest
from fakes.tokenizer import build_tokenizer, synthetic_prompt_tokenizer
from prompt_support import FOUND, LOOKUP, build

from gisting.prompt.messages import ToolMessage
from gisting.prompt.tokenizer import IM_START, PromptTokenizer, TokenizerUnavailable
from gisting.prompt.variants import (
    DEFAULT_VARIANT,
    ChatVariant,
    VariantError,
    load_variants,
    variant_for_template,
)

NO_THINK = ChatVariant("plain", "0" * 64, ())


def model_dir(tmp_path: Path, template: str | None) -> Path:
    build_tokenizer().save(str(tmp_path / "tokenizer.json"))
    if template is not None:
        config = json.dumps({"chat_template": template})
        (tmp_path / "tokenizer_config.json").write_text(config, encoding="utf-8")
    return tmp_path


def test_every_variant_is_listed_with_a_distinct_template_hash() -> None:
    variants = load_variants()
    assert DEFAULT_VARIANT in {variant.name for variant in variants}
    assert len({variant.chat_template_sha256 for variant in variants}) == len(variants)


def test_default_variant_keeps_the_empty_thinking_block() -> None:
    tokenizer = synthetic_prompt_tokenizer()
    ids = build(tokenizer, [*LOOKUP, ToolMessage(FOUND)]).ids
    assert tokenizer.decode(ids).endswith("<|im_start|>assistant\n<think>\n\n</think>\n\n")


def test_a_variant_without_a_suffix_ends_at_the_assistant_header() -> None:
    tokenizer = PromptTokenizer(build_tokenizer(), NO_THINK)
    ids = build(tokenizer, [*LOOKUP, ToolMessage(FOUND)]).ids
    assert tokenizer.decode(ids).endswith(f"{IM_START}assistant\n")


def test_variants_differ_only_after_the_assistant_header() -> None:
    default = build(synthetic_prompt_tokenizer(), LOOKUP).ids
    plain = build(PromptTokenizer(build_tokenizer(), NO_THINK), LOOKUP).ids
    assert default[: len(plain)] == plain
    assert len(default) > len(plain)


def test_from_dir_picks_the_variant_by_the_chat_template_hash(tmp_path: Path) -> None:
    template = "a template that is not in the data"
    digest = hashlib.sha256(template.encode()).hexdigest()
    with pytest.raises(TokenizerUnavailable, match=digest):
        PromptTokenizer.from_dir(model_dir(tmp_path, template))


def test_from_dir_without_tokenizer_config_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(TokenizerUnavailable, match="tokenizer_config.json"):
        PromptTokenizer.from_dir(model_dir(tmp_path, None))


def test_known_template_hash_resolves_to_its_variant() -> None:
    for variant in load_variants():
        assert variant_for_template(variant.chat_template_sha256) == variant


def test_unknown_template_hash_is_an_error() -> None:
    with pytest.raises(VariantError, match="ff" * 32):
        variant_for_template("ff" * 32)
