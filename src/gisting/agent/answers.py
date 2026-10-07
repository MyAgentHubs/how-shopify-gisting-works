import json
import re
from collections.abc import Iterable
from dataclasses import dataclass

from gisting.agent.conclusions import APOSTROPHES
from gisting.agent.consent import Patterns, compiled
from gisting.prompt.files import PROMPTS_DIR
from gisting.prompt.messages import AssistantMessage, Message, ToolMessage, UserMessage
from gisting.prompt.parcel_copy import FOR_IT_SLOT
from gisting.prompt.phrases import ReplyPhrases
from gisting.prompt.refusal import is_decline, load_decline_patterns
from gisting.prompt.replies import (
    PLACEHOLDER,
    Unrenderable,
    field_value,
    render_reply,
)
from gisting.shopify.jsonvalue import (
    Json,
    JsonObject,
    MalformedResponse,
    required_list,
    required_object,
    required_str,
    string_list,
)

DONE_CLAIMS_FILE = PROMPTS_DIR / "done_claims.json"
FOUND = "found"
FAILURES = ("unavailable", "locked")
LOOKUP_STATUSES = (FOUND, "no_match", *FAILURES)
LOOKUP = "lookup_order"
NO_TRACKING = "FULFILLED"
MISSING_TRACKING = "tracking"


@dataclass(frozen=True)
class Confirmation:
    status: str
    template: str
    field: str


@dataclass(frozen=True)
class AnswerRules:
    phrases: ReplyPhrases
    reasons: dict[str, str]
    default_reason: str
    priority: tuple[str, ...]
    status_words: dict[str, tuple[str, ...]]
    derived: dict[str, str]
    confirmations: dict[str, Confirmation]
    claims: Patterns
    promises: Patterns
    order_words: Patterns
    own_order_words: Patterns
    ask_blockers: Patterns
    refusal: str
    refusal_words: Patterns
    decline_sentences: Patterns
    claim_reply: str


def lower(text: str) -> str:
    return " ".join(text.translate(APOSTROPHES).lower().split())


def status_words(phrases: ReplyPhrases, statuses: Iterable[str]) -> dict[str, tuple[str, ...]]:
    words: dict[str, tuple[str, ...]] = {}
    for status in statuses:
        if status in FAILURES:
            found = [phrases.failure_replies[status].split(". ")[0]]
        elif status == NO_TRACKING:
            found = [
                phrases.no_shipment_details.split(",")[0],
                phrases.parcels.missing[MISSING_TRACKING].split(FOR_IT_SLOT)[0],
            ]
        else:
            found = [phrases.transport_status[status], phrases.parcels.status[status]]
        words[status] = tuple(dict.fromkeys(lower(word) for word in found))
    return words


def parse_confirmations(node: JsonObject, phrases: ReplyPhrases) -> dict[str, Confirmation]:
    found: dict[str, Confirmation] = {}
    for tool in node:
        item = required_object(node, tool)
        sentence = required_str(item, "sentence")
        if sentence not in phrases.sentences:
            raise MalformedResponse("confirmations")
        found[tool] = Confirmation(
            required_str(item, "status"), phrases.sentences[sentence], required_str(item, "field")
        )
    return found


def parse_answer_rules(node: JsonObject, phrases: ReplyPhrases) -> AnswerRules:
    reasons = required_object(node, "handoff_reasons")
    by_status = required_object(reasons, "by_status")
    priority = tuple(string_list(reasons, "priority"))
    if set(priority) != set(by_status) or len(priority) != len(by_status):
        raise MalformedResponse("priority")
    claim_reply = required_str(node, "claim_reply")
    claims = json.loads(DONE_CLAIMS_FILE.read_text(encoding="utf-8"))
    if claim_reply not in phrases.sentences:
        raise MalformedResponse("claim_reply")
    try:
        found = compiled(claims, "claims")
    except re.error as error:
        raise MalformedResponse("answers") from error
    derived = required_object(node, "derived")
    return AnswerRules(
        phrases=phrases,
        reasons={status: required_str(by_status, status) for status in by_status},
        default_reason=required_str(reasons, "default"),
        priority=priority,
        status_words=status_words(phrases, priority),
        derived={tool: required_str(derived, tool) for tool in derived},
        confirmations=parse_confirmations(required_object(node, "confirmations"), phrases),
        claims=found,
        promises=compiled(claims, "promises"),
        order_words=compiled(node, "order_words"),
        own_order_words=compiled(node, "own_order_words"),
        ask_blockers=compiled(node, "ask_blockers"),
        refusal=phrases.sentences[required_str(node, "refusal_sentence")],
        refusal_words=compiled(node, "refusal_words"),
        decline_sentences=load_decline_patterns(),
        claim_reply=phrases.sentences[claim_reply],
    )


def parcel_statuses(document: JsonObject) -> list[str]:
    status = document.get("status")
    if status != FOUND:
        return [status] if isinstance(status, str) else []
    order = required_object(document, "order")
    shipments = [s for s in required_list(order, "shipments") if isinstance(s, dict)]
    transports = [field_value(node, "transport_status") for node in shipments]
    return [t for t in transports if t] or [
        t for t in [field_value(order, "fulfillment_status")] if t
    ]


def lookup_results(messages: list[Message]) -> list[JsonObject]:
    parsed: list[JsonObject] = []
    for message in messages:
        document = json_object(message.content) if isinstance(message, ToolMessage) else None
        if document is not None and document.get("status") in LOOKUP_STATUSES:
            parsed.append(document)
    return parsed


def json_object(content: str) -> JsonObject | None:
    try:
        document: Json = json.loads(content)
    except ValueError:
        return None
    return document if isinstance(document, dict) else None


def offer_text(messages: list[Message]) -> str:
    last = max((i for i, m in enumerate(messages) if isinstance(m, UserMessage)), default=0)
    texts = [m.content for m in messages[:last] if isinstance(m, AssistantMessage) and m.content]
    return lower(texts[-1]) if texts else ""


def context_status(rules: AnswerRules, messages: list[Message]) -> str | None:
    results = lookup_results(messages)
    seen = parcel_statuses(results[-1]) if results else []
    said = offer_text(messages)
    if not seen:
        seen = [s for s, words in rules.status_words.items() if any(w in said for w in words)]
    return next((status for status in rules.priority if status in seen), None)


def handoff_reason(rules: AnswerRules, messages: list[Message], *, requested: bool) -> str:
    status = None if requested else context_status(rules, messages)
    return rules.reasons.get(status or "", rules.default_reason)


def confirmation_reply(rules: AnswerRules, tool: str, result: JsonObject) -> str | None:
    confirmation = rules.confirmations.get(tool)
    value = result.get(confirmation.field) if confirmation else None
    if confirmation is None or result.get("status") != confirmation.status:
        return None
    return PLACEHOLDER.sub(str(value), confirmation.template) if value else None


def false_claim(rules: AnswerRules, text: str) -> str | None:
    for pattern in rules.claims:
        found = pattern.search(text)
        if found:
            return found.group().lower()
    return None


def false_promise(rules: AnswerRules, text: str) -> str | None:
    for pattern in rules.promises:
        found = pattern.search(text.translate(APOSTROPHES))
        if found:
            return found.group().lower()
    return None


def refusal_intent(rules: AnswerRules, text: str) -> bool:
    spoken = text.translate(APOSTROPHES)
    if any(pattern.search(spoken) for pattern in rules.refusal_words):
        return True
    return is_decline(rules.decline_sentences, text)


def lookup_reply(rules: AnswerRules, tool: str, result: JsonObject) -> str | Unrenderable | None:
    return render_reply(rules.phrases, result) if tool == LOOKUP else None


def asks_about_order(rules: AnswerRules, said: str) -> bool:
    return any(pattern.search(said) for pattern in rules.order_words)


def names_own_order(rules: AnswerRules, said: str) -> bool:
    plain = said.translate(APOSTROPHES)
    return any(pattern.search(plain) for pattern in rules.own_order_words)


def probes_rules(rules: AnswerRules, said: str) -> bool:
    plain = said.translate(APOSTROPHES)
    return any(pattern.search(plain) for pattern in rules.ask_blockers)
