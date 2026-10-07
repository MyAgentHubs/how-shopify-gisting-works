from pathlib import Path

import pytest
from fakes.tokenizer import synthetic_prompt_tokenizer

from gisting.prompt.tokenizer import IM_START, PromptTokenizer, TokenizerUnavailable


def test_missing_tokenizer_file_is_reported_with_its_path(tmp_path: Path) -> None:
    with pytest.raises(TokenizerUnavailable, match=str(tmp_path)):
        PromptTokenizer.from_dir(tmp_path)


def test_unknown_control_token_is_an_error() -> None:
    tokenizer = synthetic_prompt_tokenizer()
    assert tokenizer.control(IM_START) >= 0
    with pytest.raises(TokenizerUnavailable):
        tokenizer.control("<|nope|>")
