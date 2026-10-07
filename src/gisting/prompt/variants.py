import json
from dataclasses import dataclass
from typing import cast

from gisting.prompt.files import read_prompt
from gisting.prompt.schema import as_object

VARIANTS_FILE = "chat_variants.json"
DEFAULT_VARIANT = "qwen3-thinking-off"


class VariantError(ValueError):
    pass


@dataclass(frozen=True)
class SuffixPiece:
    text: str
    is_control: bool


@dataclass(frozen=True)
class ChatVariant:
    name: str
    chat_template_sha256: str
    generation_suffix: tuple[SuffixPiece, ...]


def parse_piece(item: object) -> SuffixPiece:
    piece = as_object(item)
    if piece is None or len(piece) != 1:
        message = "a suffix piece must be an object with exactly one of control or text"
        raise VariantError(message)
    kind, text = next(iter(piece.items()))
    if kind not in ("control", "text") or not isinstance(text, str) or not text:
        message = f"bad suffix piece {kind}"
        raise VariantError(message)
    return SuffixPiece(text, kind == "control")


def parse_variant(item: object) -> ChatVariant:
    entry = as_object(item)
    if entry is None:
        message = "a variant must be an object"
        raise VariantError(message)
    name, digest, suffix = (
        entry.get("name"),
        entry.get("chat_template_sha256"),
        entry.get("generation_suffix"),
    )
    if not isinstance(name, str) or not isinstance(digest, str) or not isinstance(suffix, list):
        message = "a variant needs name, chat_template_sha256 and generation_suffix"
        raise VariantError(message)
    pieces = tuple(parse_piece(piece) for piece in cast(list[object], suffix))
    return ChatVariant(name, digest, pieces)


def load_variants() -> tuple[ChatVariant, ...]:
    document = as_object(json.loads(read_prompt(VARIANTS_FILE)))
    listed = None if document is None else document.get("variants")
    if not isinstance(listed, list):
        message = f"{VARIANTS_FILE} needs a variants list"
        raise VariantError(message)
    return tuple(parse_variant(item) for item in cast(list[object], listed))


def default_variant() -> ChatVariant:
    return next(variant for variant in load_variants() if variant.name == DEFAULT_VARIANT)


def variant_for_template(digest: str) -> ChatVariant:
    for variant in load_variants():
        if variant.chat_template_sha256 == digest:
            return variant
    message = f"no chat variant for chat template sha256 {digest}; add it to {VARIANTS_FILE}"
    raise VariantError(message)
