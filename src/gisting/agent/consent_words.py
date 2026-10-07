import re
from collections.abc import Sequence
from dataclasses import dataclass

from gisting.agent.conclusions import APOSTROPHES
from gisting.shopify.jsonvalue import JsonObject, MalformedResponse, required_str, string_list

STRONG = "strong"
WEAK = "weak"
COURTESY = "courtesy"
REFUSAL = "refusal"
KINDS = (STRONG, WEAK, COURTESY, REFUSAL)
SPOKEN = re.compile(r"[^\W_]+(?:'[^\W_]+)*")

Entries = tuple[tuple[tuple[str, ...], str], ...]


@dataclass(frozen=True)
class Vocabulary:
    entries: Entries
    questions: re.Pattern[str]
    marks: re.Pattern[str]
    references: re.Pattern[str]


def spoken(text: str) -> list[str]:
    return SPOKEN.findall(text.translate(APOSTROPHES).lower())


def parse_vocabulary(node: JsonObject, extra_strong: Sequence[str] = ()) -> Vocabulary:
    found: dict[tuple[str, ...], str] = {}
    for kind in KINDS:
        phrases = [*string_list(node, kind), *(extra_strong if kind == STRONG else ())]
        for phrase in phrases:
            tokens = tuple(spoken(phrase))
            if not tokens or found.setdefault(tokens, kind) != kind:
                raise MalformedResponse("consent_words")
    try:
        questions = re.compile(required_str(node, "questions"))
        marks = re.compile(required_str(node, "marks"))
        references = re.compile(required_str(node, "references"))
    except re.error as error:
        raise MalformedResponse("consent_words") from error
    entries = tuple(sorted(found.items(), key=lambda item: -len(item[0])))
    return Vocabulary(entries, questions, marks, references)


def kinds_of(vocabulary: Vocabulary, text: str) -> set[str] | None:
    words = spoken(text)
    reached: list[set[str] | None] = [set(), *([None] * len(words))]
    for at in range(len(words)):
        before = reached[at]
        if before is None:
            continue
        for tokens, kind in vocabulary.entries:
            end = at + len(tokens)
            if tuple(words[at:end]) == tokens and reached[end] is None:
                reached[end] = before | {kind}
    return reached[-1]


def is_question(vocabulary: Vocabulary, text: str) -> bool:
    return bool(vocabulary.questions.search(text))


def only_marks_between_words(vocabulary: Vocabulary, text: str) -> bool:
    rest = SPOKEN.sub("", text.translate(APOSTROPHES).lower())
    return bool(vocabulary.marks.fullmatch(rest))


def plain_agreement(vocabulary: Vocabulary, said: str) -> bool:
    kinds = kinds_of(vocabulary, said)
    if kinds is None or vocabulary.references.search(said) or kinds & {REFUSAL}:
        return False
    if not only_marks_between_words(vocabulary, said):
        return False
    return bool(kinds & {STRONG, WEAK}) and (COURTESY not in kinds or STRONG in kinds)


def plain_refusal(vocabulary: Vocabulary, said: str) -> bool:
    kinds = kinds_of(vocabulary, said)
    if kinds is None or vocabulary.references.search(said) or is_question(vocabulary, said):
        return False
    return REFUSAL in kinds and kinds <= {REFUSAL, COURTESY}
