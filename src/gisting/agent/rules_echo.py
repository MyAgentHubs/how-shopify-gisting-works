import re
from dataclasses import dataclass

from gisting.agent.conclusions import APOSTROPHES
from gisting.prompt.phrases import ReplyPhrases
from gisting.prompt.rules import rules_text
from gisting.prompt.schema import as_object, load_tool_schemas
from gisting.shopify.jsonvalue import JsonObject, MalformedResponse, required_int, string_list

QUOTED = re.compile(r'"[^"]*"|“[^”]*”')
WORD = re.compile(r"[a-z']+")
MIN_WORDS = 3

Grams = frozenset[tuple[str, ...]]


@dataclass(frozen=True)
class RulesEcho:
    words: int
    max_shared: int
    rules_grams: Grams
    approved_grams: Grams
    leak_markers: re.Pattern[str]
    quotable_markers: re.Pattern[str]


def tokens(text: str) -> list[str]:
    return WORD.findall(text.translate(APOSTROPHES).lower())


def grams(text: str, words: int) -> Grams:
    found = tokens(text)
    return frozenset(tuple(found[i : i + words]) for i in range(len(found) - words + 1))


def approved_sentences(phrases: ReplyPhrases) -> list[str]:
    return [
        *phrases.sentences.values(),
        *phrases.ask.values(),
        *phrases.ask_bare.values(),
        *phrases.failure_replies.values(),
    ]


def rules_body(phrases: ReplyPhrases, skip: int) -> str:
    paragraphs = rules_text(phrases).split("\n\n")[skip:]
    return QUOTED.sub(" ", "\n\n".join(paragraphs))


def tool_texts() -> str:
    texts: list[str] = []
    for schema in load_tool_schemas().values():
        properties = as_object(schema.parameters.get("properties")) or {}
        notes = [(as_object(field) or {}).get("description") for field in properties.values()]
        texts.append(" ".join([schema.description, *(n for n in notes if isinstance(n, str))]))
    return "\n\n".join(texts)


def marker_pattern(markers: tuple[str, ...]) -> re.Pattern[str]:
    ordered = sorted(markers, key=len, reverse=True)
    alternatives = "|".join(re.escape(marker).replace(r"\ ", r"\s+") for marker in ordered)
    if not alternatives:
        return re.compile(r"(?!)")
    return re.compile(rf"(?<!\w)(?:{alternatives})(?!\w)", re.IGNORECASE)


def parse_rules_echo(node: JsonObject, phrases: ReplyPhrases) -> RulesEcho:
    words = required_int(node, "words")
    max_shared = required_int(node, "max_shared")
    skip = required_int(node, "skip_paragraphs")
    if words < MIN_WORDS or max_shared < 0 or skip < 0:
        raise MalformedResponse("rules_echo")
    approved: Grams = frozenset()
    for text in approved_sentences(phrases):
        approved |= grams(text, words)
    source = f"{rules_body(phrases, skip)}\n\n{tool_texts()}"
    leak = string_list(node, "leak_markers")
    quotable = string_list(node, "quotable_markers")
    if not leak or not all(leak) or not set(quotable) <= set(leak):
        raise MalformedResponse("leak_markers")
    return RulesEcho(
        words,
        max_shared,
        grams(source, words),
        approved,
        marker_pattern(leak),
        marker_pattern(quotable),
    )


def marker_key(found: str) -> str:
    return " ".join(found.lower().split()).removesuffix("s")


def echoed_rules(echo: RulesEcho, said: str, customer_said: str = "") -> str | None:
    spoken = {marker_key(m.group(0)) for m in echo.quotable_markers.finditer(customer_said)}
    for marker in echo.leak_markers.finditer(said):
        if marker_key(marker.group(0)) not in spoken:
            return marker.group(0).lower()
    shared = (grams(said, echo.words) & echo.rules_grams) - echo.approved_grams
    if len(shared) <= echo.max_shared:
        return None
    return " ".join(min(shared))
