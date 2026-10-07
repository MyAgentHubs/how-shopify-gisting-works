import re
from dataclasses import dataclass

from gisting.prompt.parcel_copy import ONE, SHIPPED
from gisting.prompt.parcel_render import (
    Details,
    Node,
    details_of,
    field_value,
    objects,
    one_sentence,
    several_sentence,
)
from gisting.prompt.phrases import ReplyPhrases
from gisting.prompt.schema import as_object

PLACEHOLDER = re.compile(r"<([^<>]+)>")
MONTH_SLOT = "month name"
SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+")
FOUND = "found"
FULFILLMENT = "fulfillment_status"
TRANSPORT = "transport_status"
UNSHIPPED = "UNFULFILLED"
PARTIAL = "PARTIALLY_FULFILLED"


@dataclass(frozen=True)
class Unrenderable:
    reason: str


class UnrenderableReply(ValueError):
    pass


def fulfillment_of(order: Node) -> str:
    return field_value(order, "fulfillment_status") or ""


def status_key(phrases: ReplyPhrases, order: Node) -> tuple[str, str]:
    fulfillment = fulfillment_of(order)
    shipments = objects(order, "shipments")
    if shipments and fulfillment not in phrases.reply_by_status[FULFILLMENT]:
        return TRANSPORT, field_value(shipments[0], "transport_status") or ""
    return FULFILLMENT, fulfillment


def line_text(phrases: ReplyPhrases, table: str, status: str) -> str:
    words = getattr(phrases, table)[status]
    return phrases.reply_by_status[table][status].format(words=words, **phrases.sentences)


def fill_slots(template: str, details: Details) -> str:
    values = {
        "carrier": details.carrier,
        "tracking number": details.tracking,
        MONTH_SLOT: details.day,
    }

    def value(match: re.Match[str]) -> str:
        key = MONTH_SLOT if match.group(1).startswith(MONTH_SLOT) else match.group(1)
        return values.get(key) or match.group(0)

    return PLACEHOLDER.sub(value, template)


def lists_parcels(phrases: ReplyPhrases, order: Node, shipments: list[Node]) -> bool:
    table, status = status_key(phrases, order)
    listed = table == TRANSPORT or status in phrases.parcels.closing_when
    return len(shipments) >= phrases.limits.parcels_from(fulfillment_of(order)) and listed


def closing_sentences(phrases: ReplyPhrases, statuses: set[str], *, one: bool = False) -> list[str]:
    copy = phrases.parcels
    table = copy.closing_when_one if one else copy.closing_when
    wanted = {name for status in statuses for name in table.get(status, ())}
    return [phrases.sentences[name] for name in copy.closing_order if name in wanted]


def render_parcels(phrases: ReplyPhrases, order: Node, shipments: list[Node]) -> str:
    fulfillment = fulfillment_of(order)
    statuses = {field_value(node, "transport_status") or "" for node in shipments}
    statuses.add(fulfillment)
    limits = phrases.limits
    parcels = [several_sentence(phrases.parcels, i, node) for i, node in enumerate(shipments)]
    closing = closing_sentences(phrases, statuses)
    lead = (
        template_sentences(phrases, FULFILLMENT, fulfillment)
        if len(shipments) < limits.several_parcels_from
        else []
    )
    count = len(lead) + len(parcels) + len(closing)
    if len(parcels) > limits.max_parcels or count > limits.sentence_limit(statuses):
        return phrases.parcels.many_reply
    return " ".join([*lead, *parcels, *closing])


def template_sentences(phrases: ReplyPhrases, table: str, status: str) -> list[str]:
    return SENTENCE_BREAK.split(line_text(phrases, table, status))


def base_sentences(phrases: ReplyPhrases, status: str) -> list[str]:
    if status != PARTIAL:
        return template_sentences(phrases, TRANSPORT, status)
    return template_sentences(phrases, FULFILLMENT, status)


def without_closing(phrases: ReplyPhrases, sentences: list[str]) -> list[str]:
    closing = {phrases.sentences[name] for name in phrases.parcels.closing_order}
    return [sentence for sentence in sentences if sentence not in closing]


def without_details(phrases: ReplyPhrases, sentences: list[str]) -> list[str]:
    kept = [part for part in sentences if not PLACEHOLDER.search(part)]
    return [kept[0], phrases.no_shipment_details, *kept[1:]]


def opening_of(phrases: ReplyPhrases, transport: str) -> str:
    return f"{phrases.parcels.forms[ONE].subject} {phrases.parcels.status[transport]}"


def head_sentences(phrases: ReplyPhrases, node: Node, base: list[str]) -> list[str]:
    transport, details = field_value(node, "transport_status"), details_of(node)
    if transport == SHIPPED and details.bare:
        return base
    if transport != SHIPPED and details.full:
        return [fill_slots(sentence, details) for sentence in base]
    if transport is not None:
        return [one_sentence(phrases.parcels, opening_of(phrases, transport), node)]
    return without_details(phrases, base)


def render_one(phrases: ReplyPhrases, order: Node, shipments: list[Node]) -> str:
    table, status = status_key(phrases, order)
    if status == UNSHIPPED:
        return line_text(phrases, table, status)
    node: Node = shipments[0] if shipments else {}
    transport = field_value(node, "transport_status")
    base = without_closing(phrases, base_sentences(phrases, status))
    untracked = field_value(node, "tracking_number") is None
    closing = closing_sentences(phrases, {status, transport or ""}, one=untracked)
    return " ".join([*head_sentences(phrases, node, base), *closing])


def unrenderable_reason(phrases: ReplyPhrases, order: Node, shipments: list[Node]) -> str | None:
    fulfillment = field_value(order, "fulfillment_status")
    if fulfillment not in phrases.fulfillment_status:
        return f"fulfillment_status:{fulfillment}"
    if fulfillment == UNSHIPPED:
        return None
    if not shipments and fulfillment not in phrases.reply_by_status[FULFILLMENT]:
        return f"no_shipments:{fulfillment}"
    for node in shipments:
        transport = field_value(node, "transport_status")
        if transport not in phrases.transport_status:
            return f"transport_status:{transport}"
    return None


def render_found(phrases: ReplyPhrases, order: Node) -> str | Unrenderable:
    shipments = objects(order, "shipments")
    reason = unrenderable_reason(phrases, order, shipments)
    if reason is not None:
        return Unrenderable(reason)
    if lists_parcels(phrases, order, shipments):
        return render_parcels(phrases, order, shipments)
    return render_one(phrases, order, shipments)


def render_reply(phrases: ReplyPhrases, result: Node) -> str | Unrenderable:
    status = result.get("status")
    if status == FOUND:
        return render_found(phrases, as_object(result.get("order")) or {})
    reply = phrases.failure_replies.get(str(status))
    return reply if reply is not None else Unrenderable(f"result_status:{status}")


def fixed_reply(phrases: ReplyPhrases, result: Node) -> str:
    reply = render_reply(phrases, result)
    if isinstance(reply, Unrenderable):
        raise UnrenderableReply(reply.reason)
    return reply
