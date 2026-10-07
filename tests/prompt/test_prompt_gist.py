import pytest
from fakes.real_model import MODEL_DIR, needs_tokenizer
from fakes.tokenizer import added_ids, build_tokenizer, synthetic_prompt_tokenizer
from hypothesis import given
from hypothesis import strategies as st
from prompt_support import FOUND, LOOKUP, PAYLOADS_FOR_GIST, build

from gisting.prompt.assemble import gist_rules
from gisting.prompt.fingerprint import rules_sha256, tools_sha256
from gisting.prompt.messages import ToolMessage
from gisting.prompt.tokenizer import PromptTokenizer

K = 16


def test_placeholder_is_above_every_id_the_tokenizer_can_emit() -> None:
    tokenizer = synthetic_prompt_tokenizer()
    every = set(build_tokenizer().get_vocab(with_added_tokens=True).values())
    assert tokenizer.gist_placeholder == max(every) + 1
    assert tokenizer.gist_placeholder not in every


@needs_tokenizer
def test_real_placeholder_is_inside_the_padding_rows_of_the_embedding() -> None:
    tokenizer = PromptTokenizer.from_dir(MODEL_DIR)
    assert 151_669 <= tokenizer.gist_placeholder < 151_936


@pytest.mark.parametrize("payload", PAYLOADS_FOR_GIST)
def test_user_tool_and_assistant_text_never_encode_to_the_placeholder(payload: str) -> None:
    tokenizer = synthetic_prompt_tokenizer()
    ids = build(tokenizer, [*LOOKUP, ToolMessage(payload)]).ids
    assert tokenizer.gist_placeholder not in ids
    assert tokenizer.gist_placeholder not in tokenizer.encode_trusted(payload)


@given(st.text())
def test_arbitrary_text_never_encodes_to_the_placeholder(text: str) -> None:
    tokenizer = synthetic_prompt_tokenizer()
    assert tokenizer.gist_placeholder not in tokenizer.encode_text(text)


def test_every_added_token_string_stays_below_the_placeholder() -> None:
    tokenizer = synthetic_prompt_tokenizer()
    assert max(added_ids(build_tokenizer()).values()) < tokenizer.gist_placeholder


def test_gist_rules_are_k_placeholders_and_only_the_rules_segment_shrinks() -> None:
    tokenizer = synthetic_prompt_tokenizer()
    full = build(tokenizer, [*LOOKUP, ToolMessage(FOUND)])
    gist = build(tokenizer, [*LOOKUP, ToolMessage(FOUND)], rules=gist_rules(tokenizer, K))
    assert gist.ids.count(tokenizer.gist_placeholder) == K
    assert gist.stats.rules < full.stats.rules
    assert (gist.stats.tools, gist.stats.history, gist.stats.tool_results) == (
        full.stats.tools,
        full.stats.history,
        full.stats.tool_results,
    )


def test_gist_rules_need_at_least_one_placeholder() -> None:
    with pytest.raises(ValueError, match="at least one"):
        gist_rules(synthetic_prompt_tokenizer(), 0)


def test_fingerprints_are_stable_hex_digests() -> None:
    tokenizer = synthetic_prompt_tokenizer()
    assert rules_sha256() == rules_sha256()
    assert tools_sha256(tokenizer) == tools_sha256(tokenizer)
    assert len(rules_sha256()) == len(tools_sha256(tokenizer)) == 64
