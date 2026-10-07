import json
import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from gisting.shopify.jsonvalue import Json, MalformedResponse, required_int, string_list

SLOT_MARK = ""
WORD = re.compile(rf"[\w']+|{SLOT_MARK}")


@dataclass(frozen=True)
class Policy:
    ngram_words: int
    min_words: int
    max_shared_ngrams: int
    slots: tuple[re.Pattern[str], ...]


@dataclass(frozen=True)
class Text:
    label: str
    tokens: tuple[str, ...]


@dataclass(frozen=True)
class Hit:
    candidate: str
    reference: str
    shared: int


def load_policy(path: Path) -> Policy:
    try:
        document: Json = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            raise MalformedResponse("policy")
        return Policy(
            ngram_words=required_int(document, "ngram_words"),
            min_words=required_int(document, "min_words"),
            max_shared_ngrams=required_int(document, "max_shared_ngrams"),
            slots=tuple(re.compile(pattern) for pattern in string_list(document, "slots")),
        )
    except (OSError, ValueError, re.error) as error:
        message = f"contamination policy {path.name}: {type(error).__name__}: {error}"
        raise ValueError(message) from error


def tokens_of(body: str, policy: Policy) -> tuple[str, ...]:
    for slot in policy.slots:
        body = slot.sub(f" {SLOT_MARK} ", body)
    return tuple(WORD.findall(body.lower()))


def windows(tokens: tuple[str, ...], size: int) -> set[tuple[str, ...]]:
    return {tokens[start : start + size] for start in range(len(tokens) - size + 1)}


def spaced(tokens: tuple[str, ...]) -> str:
    return f" {' '.join(tokens)} "


def shared_with(
    candidate: Text, policy: Policy, grams: Mapping[tuple[str, ...], str], spans: Sequence[Text]
) -> tuple[str, int] | None:
    tokens = candidate.tokens
    if len(tokens) < policy.min_words:
        return None
    if len(tokens) >= policy.ngram_words:
        owners = [grams[gram] for gram in windows(tokens, policy.ngram_words) if gram in grams]
        return (owners[0], len(owners)) if owners else None
    needle = spaced(tokens)
    return next(((ref.label, 1) for ref in spans if needle in spaced(ref.tokens)), None)


def contaminated(
    candidates: Sequence[Text], references: Sequence[Text], policy: Policy
) -> list[Hit]:
    grams: dict[tuple[str, ...], str] = {}
    for ref in references:
        for gram in windows(ref.tokens, policy.ngram_words):
            grams.setdefault(gram, ref.label)
    hits: list[Hit] = []
    for candidate in candidates:
        found = shared_with(candidate, policy, grams, references)
        if found and found[1] > policy.max_shared_ngrams:
            hits.append(Hit(candidate.label, found[0], found[1]))
    return hits


def string_leaves(node: Json, path: str) -> Iterator[tuple[str, str]]:
    if isinstance(node, str):
        yield path, node
    elif isinstance(node, list):
        for index, item in enumerate(node):
            yield from string_leaves(item, f"{path}[{index}]")
    elif isinstance(node, dict):
        for key, item in node.items():
            yield from string_leaves(item, f"{path}.{key}" if path else str(key))


def training_texts(document: Json, policy: Policy) -> list[Text]:
    return [Text(path, tokens_of(body, policy)) for path, body in string_leaves(document, "")]


def training_family_names(node: Json) -> frozenset[str]:
    names: set[str] = set()
    if isinstance(node, dict):
        for key, item in node.items():
            if isinstance(item, dict) and "templates" in item:
                names.add(str(key))
            names |= training_family_names(item)
    return frozenset(names)
