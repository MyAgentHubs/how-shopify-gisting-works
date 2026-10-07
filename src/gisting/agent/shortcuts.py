import json
from collections.abc import Sequence
from dataclasses import dataclass

from gisting.agent.consent import agreed_offer, latest_exchange, refused_offer
from gisting.agent.guard import SEPARATOR
from gisting.agent.policy import AgentPolicy, Grounding
from gisting.prompt.messages import AssistantMessage, Message, ToolMessage, UserMessage
from gisting.prompt.replies import FOUND, field_value
from gisting.prompt.schema import as_object
from gisting.shopify.jsonvalue import JsonObject

AGREED = "agreed_offer"
DECLINED = "declined_offer"
ORDER_ARGUMENT = "order_number"


@dataclass(frozen=True)
class Shortcut:
    reason: str
    said: str
    tool: str | None
    arguments: JsonObject


def found_number(content: str) -> str | None:
    try:
        document = as_object(json.loads(content))
    except ValueError:
        return None
    order = as_object(document.get("order")) if document else None
    found = document is not None and document.get("status") == FOUND
    return field_value(order, "order_number") if found and order else None


def verified_order(messages: Sequence[Message]) -> str | None:
    numbers = (found_number(m.content) for m in reversed(messages) if isinstance(m, ToolMessage))
    return next((number for number in numbers if number), None)


def numbers_written(policy: AgentPolicy, message: Message) -> list[str]:
    if not isinstance(message, UserMessage):
        return []
    emails, numbers = policy.patterns[Grounding.EMAIL], policy.patterns[Grounding.ORDER_NUMBER]
    found: list[str] = numbers.findall(emails.sub(SEPARATOR, message.content))
    return sorted(set(found))


def order_before_offer(policy: AgentPolicy, messages: Sequence[Message]) -> str | None:
    last = max((i for i, m in enumerate(messages) if isinstance(m, UserMessage)), default=0)
    offers = [i for i, m in enumerate(messages[:last]) if isinstance(m, AssistantMessage)]
    for message in reversed(messages[: offers[-1] if offers else 0]):
        written = numbers_written(policy, message)
        if written:
            return written[0] if len(written) == 1 else None
    return None


def order_as_written(policy: AgentPolicy, messages: Sequence[Message]) -> str | None:
    return verified_order(messages) or order_before_offer(policy, messages)


def decide(policy: AgentPolicy, messages: Sequence[Message]) -> Shortcut | None:
    said = latest_exchange(messages)[0]
    for tool, guard in policy.consent_guards.items():
        if refused_offer(guard, messages):
            return Shortcut(DECLINED, said, None, {})
        if agreed_offer(guard, messages):
            if tool not in policy.grounded_arguments:
                return Shortcut(AGREED, said, tool, {})
            number = order_as_written(policy, messages)
            return Shortcut(AGREED, said, tool, {ORDER_ARGUMENT: number}) if number else None
    return None
