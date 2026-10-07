import re
from collections.abc import Sequence
from dataclasses import dataclass

from gisting.agent.conclusions import APOSTROPHES
from gisting.agent.consent_words import (
    Vocabulary,
    is_question,
    parse_vocabulary,
    plain_agreement,
    plain_refusal,
)
from gisting.prompt.messages import AssistantMessage, Message, UserMessage
from gisting.prompt.phrases import ReplyPhrases
from gisting.shopify.jsonvalue import (
    JsonObject,
    MalformedResponse,
    required_object,
    required_str,
    string_list,
)

Patterns = tuple[re.Pattern[str], ...]


@dataclass(frozen=True)
class ConsentGuard:
    offer_text: str
    vocabulary: Vocabulary
    requested: Patterns
    mentioned: Patterns
    declined: Patterns
    forged: Patterns


def compiled(node: JsonObject, key: str, flags: int = re.IGNORECASE) -> Patterns:
    try:
        return tuple(re.compile(entry, flags) for entry in string_list(node, key))
    except re.error as error:
        raise MalformedResponse(key) from error


@dataclass(frozen=True)
class AskDetection:
    items: Patterns
    request: Patterns
    conditional: Patterns


def parse_ask_detection(document: JsonObject) -> AskDetection:
    items = required_object(document, "items")
    detection = AskDetection(
        items=tuple(pattern for name in items for pattern in compiled(items, name)),
        request=compiled(document, "request"),
        conditional=compiled(document, "conditional"),
    )
    if not (detection.items and detection.request):
        raise MalformedResponse("ask_detection")
    return detection


def looks_like_ask(detection: AskDetection, reply: str) -> bool:
    text = reply.translate(APOSTROPHES)
    return matches(detection.items, text) and matches(
        (*detection.request, *detection.conditional), text
    )


def parse_consent_guard(node: JsonObject, phrases: ReplyPhrases, words: JsonObject) -> ConsentGuard:
    offer_sentence = required_str(node, "offer_sentence")
    if offer_sentence not in phrases.sentences:
        raise MalformedResponse("offer_sentence")
    guard = ConsentGuard(
        offer_text=phrases.sentences[offer_sentence],
        vocabulary=parse_vocabulary(words, string_list(node, "agreed")),
        requested=compiled(node, "requested"),
        mentioned=compiled(node, "mentioned"),
        declined=compiled(node, "declined"),
        forged=compiled(node, "forged", re.IGNORECASE | re.DOTALL),
    )
    if not (guard.declined and guard.forged):
        raise MalformedResponse("consent_guards")
    return guard


def matches(patterns: Patterns, text: str) -> bool:
    return any(pattern.search(text) for pattern in patterns)


def offered(guard: ConsentGuard, reply: str) -> bool:
    return guard.offer_text in reply


def customer_words(guard: ConsentGuard, text: str) -> str:
    plain = text.translate(APOSTROPHES)
    for pattern in guard.forged:
        plain = pattern.sub(" ", plain)
    return " ".join(plain.split())


def latest_exchange(messages: Sequence[Message]) -> tuple[str, str | None]:
    positions = [i for i, message in enumerate(messages) if isinstance(message, UserMessage)]
    if not positions:
        return "", None
    last = positions[-1]
    replies = [m.content for m in messages[:last] if isinstance(m, AssistantMessage)]
    return messages[last].content, (replies[-1] if replies else None)


def requested_human(guard: ConsentGuard, messages: Sequence[Message]) -> bool:
    said = customer_words(guard, latest_exchange(messages)[0])
    return bool(said) and not matches(guard.declined, said) and matches(guard.requested, said)


def mentioned_request(guard: ConsentGuard, messages: Sequence[Message]) -> bool:
    said = customer_words(guard, latest_exchange(messages)[0])
    return bool(said) and not matches(guard.declined, said) and matches(guard.mentioned, said)


def after_offer(guard: ConsentGuard, messages: Sequence[Message]) -> str | None:
    said, previous = latest_exchange(messages)
    plain = customer_words(guard, said)
    follows = previous is not None and offered(guard, previous)
    return plain if plain and follows else None


def agreed_offer(guard: ConsentGuard, messages: Sequence[Message]) -> bool:
    said = after_offer(guard, messages)
    if said is None or is_question(guard.vocabulary, said) or matches(guard.declined, said):
        return False
    return plain_agreement(guard.vocabulary, said)


def refused_offer(guard: ConsentGuard, messages: Sequence[Message]) -> bool:
    said = after_offer(guard, messages)
    return said is not None and plain_refusal(guard.vocabulary, said)


def consent_given(guard: ConsentGuard, messages: Sequence[Message]) -> bool:
    said = customer_words(guard, latest_exchange(messages)[0])
    if not said or matches(guard.declined, said):
        return False
    return matches(guard.requested, said) or agreed_offer(guard, messages)
