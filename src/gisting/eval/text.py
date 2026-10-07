import re
from collections.abc import Iterable

WORD_CHAR = re.compile(r"\w")
APOSTROPHES = str.maketrans({"’": "'", "‘": "'"})
TRAILING = re.compile(r"[\s.!?]+$")
WORDS = re.compile(r"[a-z']+")


def phrase(entry: str) -> re.Pattern[str]:
    start = r"(?<![\w'])" if WORD_CHAR.match(entry[0]) else ""
    end = r"(?![\w'])" if WORD_CHAR.match(entry[-1]) else ""
    return re.compile(f"{start}(?:{entry}){end}", re.IGNORECASE)


def phrases(entries: Iterable[str]) -> tuple[re.Pattern[str], ...]:
    return tuple(phrase(entry) for entry in entries)


def normalize(text: str) -> str:
    return " ".join(text.translate(APOSTROPHES).lower().split())


def first_match(patterns: Iterable[re.Pattern[str]], text: str) -> re.Match[str] | None:
    for pattern in patterns:
        found = pattern.search(text)
        if found:
            return found
    return None


def word_ngrams(text: str, size: int) -> set[tuple[str, ...]]:
    words = WORDS.findall(text.translate(APOSTROPHES).lower())
    return {tuple(words[i : i + size]) for i in range(len(words) - size + 1)}


def shares_ngram(answer: str, source: str, size: int) -> bool:
    return bool(word_ngrams(answer, size) & word_ngrams(source, size))


def canned_form(text: str) -> str:
    return TRAILING.sub("", normalize(text))


PLACEHOLDER = re.compile(r"<[^<>\s]+>")
PLACEHOLDER_VALUE = r"[\w-]+"


def canned_word(word: str) -> str:
    pieces = PLACEHOLDER.split(word)
    return PLACEHOLDER_VALUE.join(re.escape(piece) for piece in pieces)


def canned_pattern(form: str) -> re.Pattern[str]:
    return re.compile(r"\s+".join(canned_word(word) for word in form.split()), re.IGNORECASE)
