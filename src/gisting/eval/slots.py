import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from gisting.eval.case_spec import EvalCase

LETTERS = "abcd"
SLOT = re.compile(r"\{(email_[a-d])\}")
REQUEST_ROLES = ("user", "assistant")


class SlotError(ValueError):
    pass


@dataclass(frozen=True)
class Filled:
    messages: tuple[dict[str, str], ...]
    emails: dict[str, str]


def another_order(order: str, plan: Sequence[str], skip: frozenset[str]) -> str:
    start = plan.index(order) if order in plan else -1
    for step in range(1, len(plan) + 1):
        candidate = plan[(start + step) % len(plan)]
        if candidate not in skip:
            return candidate
    message = "the plan has no other order to borrow an email from"
    raise SlotError(message)


def case_orders(case: EvalCase, plan: Sequence[str]) -> dict[str, str]:
    listed = frozenset(use.order for use in case.fixtures.orders)
    orders: dict[str, str] = {}
    for letter, use in zip(LETTERS, case.fixtures.orders, strict=False):
        if use.email == "matching":
            orders[f"email_{letter}"] = use.order
        elif use.email == "wrong":
            orders[f"email_{letter}"] = another_order(use.order, plan, listed)
    return orders


def fill_text(case_id: str, text: str, emails: dict[str, str]) -> str:
    def value(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in emails:
            message = f"case {case_id}: slot {{{name}}} has no email to fill"
            raise SlotError(message)
        return emails[name]

    return SLOT.sub(value, text)


def fill_case(case: EvalCase, plan: Sequence[str], email_of: Mapping[str, str]) -> Filled:
    emails = {slot: email_of[order] for slot, order in case_orders(case, plan).items()}
    messages: list[dict[str, str]] = []
    for message in case.messages:
        if message.role not in REQUEST_ROLES or message.tool_calls:
            text = f"case {case.id}: the agent takes only plain user and assistant messages"
            raise SlotError(text)
        content = fill_text(case.id, message.content, emails)
        messages.append({"role": message.role, "content": content})
    return Filled(tuple(messages), emails)
