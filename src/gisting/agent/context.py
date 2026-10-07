import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass

from gisting.agent.guard import SEPARATOR
from gisting.agent.policy import AgentPolicy, Grounding
from gisting.agent.policy_replies import no_match_reply
from gisting.agent.shortcuts import found_number
from gisting.prompt.messages import AssistantMessage, Message, ToolMessage, UserMessage
from gisting.tools.policy import LookupPolicy
from gisting.tools.verification import in_range

MENTION = re.compile(r"(#?)(\d+)")
MAX_ORDER_DIGITS = 12


@dataclass(frozen=True)
class EarlierOrders:
    messages: list[Message]
    removed: int
    segments: int


@dataclass
class Focus:
    number: str | None = None
    email: str | None = None
    segment: int = 0
    ambiguous: bool = False

    @property
    def armed(self) -> bool:
        return self.number is not None and self.email is not None


@dataclass(frozen=True)
class Slot:
    segment: int
    armed: bool


def is_order_mention(hashed: str, digits: str, lookup: LookupPolicy) -> str | None:
    if len(digits) > MAX_ORDER_DIGITS:
        return None
    name = f"#{int(digits)}"
    return name if hashed or in_range(name, lookup) else None


def written_orders(policy: AgentPolicy, lookup: LookupPolicy, text: str) -> list[str]:
    plain = policy.patterns[Grounding.EMAIL].sub(SEPARATOR, unicodedata.normalize("NFKC", text))
    names = [is_order_mention(hashed, digits, lookup) for hashed, digits in MENTION.findall(plain)]
    return [name for name in names if name is not None]


def written_emails(policy: AgentPolicy, text: str) -> list[str]:
    return [email.casefold() for email in policy.patterns[Grounding.EMAIL].findall(text)]


def advance(focus: Focus, numbers: Sequence[str], emails: Sequence[str]) -> None:
    other_order = focus.number is not None and any(n != focus.number for n in numbers)
    other_email = focus.email is not None and any(e != focus.email for e in emails)
    if other_order or other_email or (focus.ambiguous and numbers):
        focus.segment += 1
    focus.ambiguous = len(set(numbers)) > 1 if numbers else focus.ambiguous
    focus.number = numbers[-1] if numbers else focus.number
    focus.email = emails[-1] if emails else focus.email


def slots_of(policy: AgentPolicy, lookup: LookupPolicy, messages: Sequence[Message]) -> list[Slot]:
    focus, slots = Focus(), list[Slot]()
    for message in messages:
        if isinstance(message, UserMessage):
            numbers = written_orders(policy, lookup, message.content)
            advance(focus, numbers, written_emails(policy, message.content))
        slots.append(Slot(focus.segment, focus.armed))
    return slots


def neutral_replies(policy: AgentPolicy, policy_answers: frozenset[str]) -> frozenset[str]:
    rules = policy.answers
    no_match = no_match_reply(rules.phrases)
    return frozenset({
        *policy_answers,
        *([] if no_match is None else [no_match]),
        *policy.needs_input_replies.values(),
        *policy.needs_input_bare_replies.values(),
        *policy.needs_consent_replies.values(),
        *policy.fallback_replies.values(),
        *rules.phrases.failure_replies.values(),
        rules.refusal,
        rules.claim_reply,
    })


def shows_facts(neutral: frozenset[str], message: Message, slot: Slot) -> bool:
    if isinstance(message, ToolMessage):
        return found_number(message.content) is not None
    if isinstance(message, AssistantMessage):
        return slot.armed and not message.tool_calls and message.content.strip() not in neutral
    return False


def stale_segments(
    neutral: frozenset[str], messages: Sequence[Message], slots: Sequence[Slot]
) -> frozenset[int]:
    shown = {
        slot.segment
        for m, slot in zip(messages, slots, strict=True)
        if shows_facts(neutral, m, slot)
    }
    return frozenset(shown - {slots[-1].segment}) if slots else frozenset()


def masked(message: Message, placeholder: str) -> Message | None:
    if isinstance(message, UserMessage):
        return UserMessage(placeholder)
    if isinstance(message, AssistantMessage) and not message.tool_calls:
        return AssistantMessage(placeholder)
    return None


def without_earlier_orders(
    policy: AgentPolicy,
    lookup: LookupPolicy,
    messages: Sequence[Message],
    policy_answers: frozenset[str] = frozenset(),
) -> EarlierOrders:
    slots = slots_of(policy, lookup, messages)
    stale = stale_segments(neutral_replies(policy, policy_answers), messages, slots)
    if not stale:
        return EarlierOrders(list(messages), 0, 0)
    kept: list[Message] = []
    removed = 0
    for message, slot in zip(messages, slots, strict=True):
        if slot.segment not in stale:
            kept.append(message)
            continue
        removed += 1
        replacement = masked(message, policy.dropped_placeholder)
        if replacement is not None:
            kept.append(replacement)
    return EarlierOrders(kept, removed, len(stale))
