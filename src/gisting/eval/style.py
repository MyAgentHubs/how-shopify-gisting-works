import re

from gisting.eval.data_model import GraderData
from gisting.eval.source import Source
from gisting.eval.text import canned_form, normalize


def word_count(sentence: str) -> int:
    return sum(1 for word in sentence.split() if any(char.isalnum() for char in word))


def sentence_list(text: str, data: GraderData) -> list[str]:
    parts = (part.strip() for part in data.style.sentence_break.split(text))
    return [part for part in parts if part]


def is_aside(sentence: str, data: GraderData) -> bool:
    offers = any(pattern.search(sentence) for pattern in data.found.handoff)
    return offers or canned_form(sentence) in data.found.empathy


def content_sentences(text: str, data: GraderData) -> list[str]:
    return [part for part in sentence_list(text, data) if not is_aside(part, data)]


def markdown_problems(text: str, data: GraderData) -> list[str]:
    found: list[str] = []
    for pattern in data.style.markdown:
        match = pattern.search(text)
        if match:
            found.append(f"markdown:{match.group().strip()}")
    return found


def enum_problems(text: str, source: Source, data: GraderData) -> list[str]:
    name = data.style.enum_name.search(text)
    found = [f"enum_name:{name.group()}"] if name else []
    for literal in sorted(source.enums):
        if re.search(rf"(?<!\w){re.escape(literal)}(?!\w)", text):
            found.append(f"enum_value:{literal}")
    return found


def readability_problems(text: str, data: GraderData, limit: int | None = None) -> list[str]:
    parts = content_sentences(text, data)
    found: list[str] = []
    if len(parts) > (data.style.max_sentences if limit is None else limit):
        found.append(f"too_many_sentences:{len(parts)}")
    longest = max((word_count(part) for part in parts), default=0)
    if longest > data.style.max_words_per_sentence:
        found.append(f"long_sentence:{longest}")
    spoken = [normalize(part) for part in sentence_list(text, data)]
    if len(set(spoken)) < len(spoken):
        found.append("repeated_sentence")
    return found
