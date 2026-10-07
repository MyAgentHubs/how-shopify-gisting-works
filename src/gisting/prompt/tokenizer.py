import hashlib
import json
import re
from itertools import pairwise
from pathlib import Path

from tokenizers import Tokenizer

from gisting.prompt.variants import (
    ChatVariant,
    VariantError,
    default_variant,
    variant_for_template,
)

IM_START = "<|im_start|>"
IM_END = "<|im_end|>"
TOOL_CALL = "<tool_call>"
TOOL_CALL_END = "</tool_call>"
TOOL_RESPONSE = "<tool_response>"
TOOL_RESPONSE_END = "</tool_response>"
THINK = "<think>"
THINK_END = "</think>"
TOKENIZER_FILE = "tokenizer.json"
CONFIG_FILE = "tokenizer_config.json"


class TokenizerUnavailable(Exception):
    pass


def alternatives(contents: list[str]) -> str:
    if not contents:
        return "(?!)"
    return "|".join(re.escape(text) for text in sorted(contents, key=len, reverse=True))


def variant_of(model_dir: Path) -> ChatVariant:
    path = model_dir.expanduser() / CONFIG_FILE
    if not path.is_file():
        message = f"{CONFIG_FILE} not found: {path}"
        raise TokenizerUnavailable(message)
    template = json.loads(path.read_text(encoding="utf-8")).get("chat_template")
    if not isinstance(template, str):
        message = f"{path} has no chat_template string"
        raise TokenizerUnavailable(message)
    try:
        return variant_for_template(hashlib.sha256(template.encode()).hexdigest())
    except VariantError as error:
        raise TokenizerUnavailable(str(error)) from error


class PromptTokenizer:
    def __init__(self, tokenizer: Tokenizer, variant: ChatVariant | None = None) -> None:
        tokenizer.encode_special_tokens = True
        self._tokenizer = tokenizer
        self.variant = variant or default_variant()
        added = alternatives([
            token.content for token in tokenizer.get_added_tokens_decoder().values()
        ])
        self._overlapping = re.compile(f"(?={added})")
        self._whole = re.compile(added)
        self.gist_placeholder = max(tokenizer.get_vocab(with_added_tokens=True).values()) + 1

    @classmethod
    def from_dir(cls, model_dir: Path) -> "PromptTokenizer":
        path = model_dir.expanduser() / TOKENIZER_FILE
        if not path.is_file():
            message = f"tokenizer file not found: {path}"
            raise TokenizerUnavailable(message)
        return cls(Tokenizer.from_file(str(path)), variant_of(model_dir))

    def control(self, token: str) -> int:
        token_id = self._tokenizer.token_to_id(token)
        if token_id is None:
            message = f"tokenizer has no control token {token}"
            raise TokenizerUnavailable(message)
        return token_id

    def encode_text(self, text: str) -> list[int]:
        cuts = [0, *(match.start() + 1 for match in self._overlapping.finditer(text)), len(text)]
        ids: list[int] = []
        for start, end in pairwise(cuts):
            if start < end:
                ids.extend(self._tokenizer.encode(text[start:end], add_special_tokens=False).ids)
        return ids

    def encode_trusted(self, text: str) -> list[int]:
        ids: list[int] = []
        position = 0
        for match in self._whole.finditer(text):
            ids.extend(self.encode_text(text[position : match.start()]))
            ids.append(self.control(match.group()))
            position = match.end()
        ids.extend(self.encode_text(text[position:]))
        return ids

    def decode(self, ids: list[int]) -> str:
        return self._tokenizer.decode(ids, skip_special_tokens=False)
