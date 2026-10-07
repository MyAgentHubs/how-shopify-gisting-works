import json
from dataclasses import dataclass
from pathlib import Path
from string import Formatter
from typing import cast

from gisting.prompt.files import PROMPTS_DIR
from gisting.prompt.parcel_copy import (
    ParcelCopy,
    ParcelCopyError,
    ReplyLimits,
    parse_limits,
    parse_parcels,
)
from gisting.prompt.schema import as_object

PHRASES_FILE = PROMPTS_DIR / "reply_phrases.json"
ASK_KEYS = frozenset({"both", "email", "order_number"})
EXAMPLE_KEYS = frozenset({"order_number", "email"})
FAILURE_KEYS = frozenset({"no_match", "unavailable", "locked"})
EXAMPLE_SLOT = "{value}"
REQUIRED_SENTENCES = frozenset({"no_shipment_details", "handoff_offer", "handoff_confirmation"})
STATUS_TABLES = ("fulfillment_status", "transport_status")


class PhrasesError(ValueError):
    pass


@dataclass(frozen=True)
class StepExample:
    customer: str
    order_number: str
    email: str


@dataclass(frozen=True)
class ReplyPhrases:
    ask: dict[str, str]
    ask_bare: dict[str, str]
    ask_examples: dict[str, str]
    ask_example_wrapper: str
    step_examples: tuple[StepExample, ...]
    fulfillment_status: dict[str, str]
    transport_status: dict[str, str]
    reply_by_status: dict[str, dict[str, str]]
    sentences: dict[str, str]
    empathy: tuple[str, ...]
    failure_replies: dict[str, str]
    parcels: ParcelCopy
    limits: ReplyLimits

    @property
    def example_spans(self) -> tuple[str, ...]:
        return tuple(
            self.ask_example_wrapper.replace(EXAMPLE_SLOT, value).strip()
            for value in self.ask_examples.values()
        )

    @property
    def no_shipment_details(self) -> str:
        return self.sentences["no_shipment_details"]

    @property
    def handoff_offer(self) -> str:
        return self.sentences["handoff_offer"]

    @property
    def handoff_confirmation(self) -> str:
        return self.sentences["handoff_confirmation"]


def text_map(document: dict[str, object], key: str) -> dict[str, str]:
    node = as_object(document.get(key))
    if not node or not all(isinstance(v, str) and v.strip() for v in node.values()):
        message = f"{key} must be a non-empty map of non-empty strings"
        raise PhrasesError(message)
    return {name: str(value) for name, value in node.items()}


def nested_map(document: dict[str, object], key: str) -> dict[str, dict[str, str]]:
    node = as_object(document.get(key))
    if not node:
        message = f"{key} must be a non-empty map of maps"
        raise PhrasesError(message)
    return {name: text_map(node, name) for name in node}


def text_at(document: dict[str, object], key: str) -> str:
    value = document.get(key)
    if not isinstance(value, str) or not value.strip():
        message = f"{key} must be a non-empty string"
        raise PhrasesError(message)
    return value


def step_example(item: object) -> StepExample:
    fields = as_object(item) or {}
    customer = fields.get("customer")
    if not isinstance(customer, str) or not customer:
        message = "a step example needs a customer message and a call"
        raise PhrasesError(message)
    values = text_map(fields, "call")
    if values.keys() != {"order_number", "email"}:
        message = "a call example needs exactly order_number and email"
        raise PhrasesError(message)
    return StepExample(customer, values["order_number"], values["email"])


def step_examples(document: dict[str, object]) -> tuple[StepExample, ...]:
    node = document.get("step_examples")
    items = cast(list[object], node) if isinstance(node, list) else []
    if not items:
        message = "step_examples must be a non-empty list"
        raise PhrasesError(message)
    return tuple(step_example(item) for item in items)


def consistency_problem(phrases: ReplyPhrases) -> str | None:
    tables = {name: getattr(phrases, name) for name in STATUS_TABLES}
    lines = phrases.reply_by_status
    if lines.keys() != tables.keys():
        return "reply_by_status must have exactly fulfillment_status and transport_status"
    if lines["transport_status"].keys() != tables["transport_status"].keys():
        return "every transport status needs exactly one reply line"
    unshipped = lines["fulfillment_status"].keys()
    if not unshipped or not unshipped <= tables["fulfillment_status"].keys():
        return "fulfillment reply lines must name fulfillment statuses"
    return sentence_problem(phrases) or ask_example_problem(phrases)


def sentence_problem(phrases: ReplyPhrases) -> str | None:
    if not phrases.sentences.keys() >= REQUIRED_SENTENCES:
        return f"sentences must include {sorted(REQUIRED_SENTENCES)}"
    known = {"words", *phrases.sentences}
    for table in phrases.reply_by_status.values():
        for line in table.values():
            names = {name for _, name, _, _ in Formatter().parse(line) if name}
            if not names <= known:
                return f"reply line uses an unknown placeholder: {sorted(names - known)}"
            if "<" in line.split(".")[0]:
                return "a reply line must open with a sentence that has no slot"
    return None


def ask_example_problem(phrases: ReplyPhrases) -> str | None:
    wanted = {
        "both": ("order_number", "email"),
        "email": ("email",),
        "order_number": ("order_number",),
    }
    for key, items in wanted.items():
        if any(phrases.ask_examples[item] not in phrases.ask[key] for item in items):
            return f"the {key} ask must carry its example values"
        if any(phrases.ask_examples[item] in phrases.ask_bare[key] for item in items):
            return f"the {key} ask without examples must not carry them"
    return None


def render_asks(
    document: dict[str, object],
) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    templates = text_map(document, "ask")
    examples = text_map(document, "ask_examples")
    wrapper = text_at(document, "ask_example_wrapper")
    if (
        templates.keys() != ASK_KEYS
        or examples.keys() != EXAMPLE_KEYS
        or EXAMPLE_SLOT not in wrapper
    ):
        message = f"ask needs the keys {sorted(ASK_KEYS)} and ask_examples {sorted(EXAMPLE_KEYS)}"
        raise PhrasesError(message)
    shown = {item: wrapper.replace(EXAMPLE_SLOT, value) for item, value in examples.items()}
    hidden = dict.fromkeys(examples, "")
    full = {
        key: text.format(**{f"{i}_example": v for i, v in shown.items()})
        for key, text in templates.items()
    }
    bare = {
        key: text.format(**{f"{i}_example": v for i, v in hidden.items()})
        for key, text in templates.items()
    }
    return full, bare, examples


def empathy_texts(document: dict[str, object], sentences: dict[str, str]) -> tuple[str, ...]:
    names = document.get("empathy")
    listed = cast(list[object], names) if isinstance(names, list) else []
    if not listed or not all(isinstance(n, str) and n in sentences for n in listed):
        message = "empathy must list names from sentences"
        raise PhrasesError(message)
    return tuple(sentences[str(name)] for name in listed)


def failure_replies(document: dict[str, object], sentences: dict[str, str]) -> dict[str, str]:
    templates = text_map(document, "failure_replies")
    if templates.keys() != FAILURE_KEYS:
        message = f"failure_replies must have exactly the keys {sorted(FAILURE_KEYS)}"
        raise PhrasesError(message)
    try:
        return {key: text.format(**sentences) for key, text in templates.items()}
    except KeyError as error:
        message = f"failure_replies uses an unknown sentence: {error}"
        raise PhrasesError(message) from error


def build_phrases(document: dict[str, object]) -> ReplyPhrases:
    ask, bare, examples = render_asks(document)
    sentences = text_map(document, "sentences")
    transports = text_map(document, "transport_status")
    try:
        limits = parse_limits(document)
        parcels = parse_parcels(document, sentences, transports, limits)
    except (ParcelCopyError, KeyError) as error:
        message = f"parcel copy: {error}"
        raise PhrasesError(message) from error
    return ReplyPhrases(
        ask=ask,
        ask_bare=bare,
        ask_examples=examples,
        ask_example_wrapper=text_at(document, "ask_example_wrapper"),
        step_examples=step_examples(document),
        fulfillment_status=text_map(document, "fulfillment_status"),
        transport_status=transports,
        reply_by_status=nested_map(document, "reply_by_status"),
        sentences=sentences,
        empathy=empathy_texts(document, sentences),
        failure_replies=failure_replies(document, sentences),
        parcels=parcels,
        limits=limits,
    )


def parse_phrases(text: str) -> ReplyPhrases:
    document = as_object(json.loads(text))
    if document is None:
        message = "reply phrases must be an object"
        raise PhrasesError(message)
    phrases = build_phrases(document)
    problem = consistency_problem(phrases)
    if problem:
        raise PhrasesError(problem)
    return phrases


def load_phrases(path: Path = PHRASES_FILE) -> ReplyPhrases:
    try:
        return parse_phrases(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        message = f"{type(error).__name__}: {error}"
        raise PhrasesError(message) from error
