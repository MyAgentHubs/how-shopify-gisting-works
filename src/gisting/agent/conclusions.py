import json
import re
from dataclasses import dataclass
from pathlib import Path

from gisting.prompt.files import PROMPTS_DIR
from gisting.shopify.jsonvalue import Json, MalformedResponse, string_list

CONCLUSIONS_FILE = PROMPTS_DIR / "query_conclusions.json"
APOSTROPHES = str.maketrans({"’": "'", "‘": "'"})


@dataclass(frozen=True)
class Conclusion:
    reason: str
    matched: str


@dataclass(frozen=True)
class Conclusions:
    groups: tuple[tuple[str, tuple[re.Pattern[str], ...]], ...]


def whole_phrase(entry: str) -> re.Pattern[str]:
    try:
        return re.compile(rf"(?<![\w'])(?:{entry})(?![\w'])", re.IGNORECASE)
    except re.error as error:
        raise MalformedResponse("conclusions") from error


def parse_conclusions(text: str) -> Conclusions:
    document: Json = json.loads(text)
    if not isinstance(document, dict) or not document:
        raise MalformedResponse("conclusions")
    groups = tuple(
        (reason, tuple(whole_phrase(entry) for entry in string_list(document, reason)))
        for reason in document
    )
    if not all(patterns for _, patterns in groups):
        raise MalformedResponse("conclusions")
    return Conclusions(groups)


def load_conclusions(path: Path = CONCLUSIONS_FILE) -> Conclusions:
    return parse_conclusions(path.read_text(encoding="utf-8"))


def find_conclusion(conclusions: Conclusions, text: str) -> Conclusion | None:
    normalized = text.translate(APOSTROPHES)
    for reason, patterns in conclusions.groups:
        for pattern in patterns:
            found = pattern.search(normalized)
            if found:
                return Conclusion(reason, found.group())
    return None
