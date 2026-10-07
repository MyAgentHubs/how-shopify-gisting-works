import re
from collections.abc import Sequence
from typing import cast

from gisting.agent.answers import asks_about_order, names_own_order, probes_rules
from gisting.agent.consent import consent_given
from gisting.agent.policy import BOTH_MISSING, AgentPolicy, Grounding
from gisting.prompt.messages import Message, UserMessage
from gisting.shopify.jsonvalue import Json, JsonObject
from gisting.shopify.order_name import ORDER_NAME

STATUS_KEY = "status"
SEPARATOR = " "
HASH = "#"
TRACKING_GROUP = "tracking_token"
ASK_ORDER = (Grounding.ORDER_NUMBER, Grounding.EMAIL)


def user_texts(messages: Sequence[Message]) -> list[str]:
    return [m.content for m in messages if isinstance(m, UserMessage)]


def email_grounded(policy: AgentPolicy, value: str, texts: Sequence[str]) -> bool:
    pattern = policy.patterns[Grounding.EMAIL]
    return value == value.strip() and any(value in pattern.findall(text) for text in texts)


def digits_in(pattern: re.Pattern[str], text: str) -> list[str]:
    return [token.removeprefix("#") for token in pattern.findall(text)]


def order_number_grounded(policy: AgentPolicy, value: str, texts: Sequence[str]) -> bool:
    shape = ORDER_NAME.fullmatch(value)
    if shape is None:
        return False
    emails, numbers = policy.patterns[Grounding.EMAIL], policy.patterns[Grounding.ORDER_NUMBER]
    return any(shape.group(1) in digits_in(numbers, emails.sub(SEPARATOR, text)) for text in texts)


class UngroundableKind(ValueError):
    pass


def is_grounded(policy: AgentPolicy, kind: Grounding, value: Json, texts: Sequence[str]) -> bool:
    if kind not in ASK_ORDER:
        message = f"grounding kind {kind.value} has no input guard"
        raise UngroundableKind(message)
    if not isinstance(value, str):
        return False
    if kind is Grounding.EMAIL:
        return email_grounded(policy, value, texts)
    return order_number_grounded(policy, value, texts)


def searches_only(rules: dict[str, Grounding]) -> bool:
    return bool(rules) and all(kind is Grounding.QUERY_TERMS for kind in rules.values())


def missing_inputs(
    policy: AgentPolicy, name: str, arguments: JsonObject, texts: Sequence[str]
) -> list[str]:
    rules = policy.grounded_arguments.get(name, {})
    if searches_only(rules):
        return []
    return [
        arg
        for arg, kind in rules.items()
        if not is_grounded(policy, kind, arguments.get(arg), texts)
    ]


def needs_input_status(policy: AgentPolicy) -> str:
    return str(policy.needs_input_result[STATUS_KEY])


def needs_consent_status(policy: AgentPolicy) -> str:
    return str(policy.needs_consent_result[STATUS_KEY])


def consent_missing(policy: AgentPolicy, name: str, messages: Sequence[Message]) -> list[str]:
    guard = policy.consent_guards.get(name)
    if guard is None or consent_given(guard, messages):
        return []
    return [str(item) for item in cast(list[object], policy.needs_consent_result["missing"])]


def provided(policy: AgentPolicy, kind: Grounding, texts: Sequence[str]) -> bool:
    pattern = policy.patterns[kind]
    if kind is Grounding.EMAIL:
        return any(pattern.search(text) for text in texts)
    emails = policy.patterns[Grounding.EMAIL]
    return any(pattern.search(emails.sub(SEPARATOR, text)) for text in texts)


def unprovided_inputs(policy: AgentPolicy, texts: Sequence[str]) -> list[str]:
    return [kind.value for kind in ASK_ORDER if not provided(policy, kind, texts)]


def related_to_order(policy: AgentPolicy, said: str, previous: str | None) -> bool:
    given = len(unprovided_inputs(policy, [said])) < len(ASK_ORDER)
    hinted = any(hint.search(said) for hint in policy.order_hints)
    return (
        asks_about_order(policy.answers, said)
        or given
        or hinted
        or answers_our_question(policy, previous)
    )


def answers_our_question(policy: AgentPolicy, previous: str | None) -> bool:
    if previous is None:
        return False
    offers = (guard.offer_text for guard in policy.consent_guards.values())
    asks = (*policy.needs_input_replies.values(), *policy.needs_input_bare_replies.values())
    return any(text in previous for text in (*offers, *asks))


def ask_reply(policy: AgentPolicy, missing: Sequence[str]) -> str:
    names = set(missing)
    key = names.pop() if len(names) == 1 else BOTH_MISSING
    return policy.needs_input_replies[key]


def cites_order_reference(policy: AgentPolicy, said: str) -> bool:
    tracking = (
        pattern
        for group, patterns in policy.conclusions.groups
        if group == TRACKING_GROUP
        for pattern in patterns
    )
    emails = policy.patterns[Grounding.EMAIL]
    tokens: list[str] = policy.patterns[Grounding.ORDER_NUMBER].findall(emails.sub(SEPARATOR, said))
    return any(token.startswith(HASH) for token in tokens) or any(
        pattern.search(said) for pattern in tracking
    )


def asks_for_own_order(policy: AgentPolicy, said: str, previous: str | None) -> bool:
    if probes_rules(policy.answers, said):
        return False
    return (
        names_own_order(policy.answers, said)
        or cites_order_reference(policy, said)
        or answers_our_question(policy, previous)
    )
