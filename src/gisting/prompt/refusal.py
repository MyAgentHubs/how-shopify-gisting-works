import json
import re
from typing import cast

from gisting.prompt.files import PROMPTS_DIR
from gisting.prompt.schema import as_object

REFUSAL_FILE = PROMPTS_DIR / "refusal_words.json"
APOSTROPHES = str.maketrans({"’": "'", "‘": "'"})
SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
TRAILING = re.compile(r"[\s.!?]+$")

Patterns = tuple[re.Pattern[str], ...]


class RefusalWordsError(ValueError):
    pass


def load_decline_patterns() -> Patterns:
    document = as_object(json.loads(REFUSAL_FILE.read_text(encoding="utf-8"))) or {}
    node = document.get("decline")
    entries = cast(list[object], node) if isinstance(node, list) else []
    if not entries or not all(isinstance(entry, str) for entry in entries):
        message = "decline must be a non-empty list of patterns"
        raise RefusalWordsError(message)
    return tuple(re.compile(str(entry), re.IGNORECASE) for entry in entries)


def spoken_sentences(text: str) -> list[str]:
    plain = " ".join(text.translate(APOSTROPHES).lower().split())
    parts = (TRAILING.sub("", part) for part in SENTENCE_END.split(plain))
    return [part for part in parts if part]


def is_decline(patterns: Patterns, text: str) -> bool:
    parts = spoken_sentences(text)
    return bool(parts) and all(any(p.fullmatch(part) for p in patterns) for part in parts)
