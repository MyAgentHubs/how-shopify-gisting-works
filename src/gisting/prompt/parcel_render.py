from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import cast

from gisting.prompt.parcel_copy import (
    FOR_IT_SLOT,
    ONE,
    ORDINAL_SLOT,
    SEVERAL,
    VALUE_SLOT,
    ParcelCopy,
    ParcelForm,
)
from gisting.prompt.schema import as_object

Node = Mapping[str, object]
DELIVERED = "DELIVERED"


def objects(node: Node, key: str) -> list[Node]:
    items = node.get(key)
    listed = cast(list[object], items) if isinstance(items, list) else []
    return [cast(Node, item) for item in listed if isinstance(item, dict)]


def field_value(node: Node, key: str) -> str | None:
    field = as_object(node.get(key))
    value = field.get("value") if field is not None else None
    return value if isinstance(value, str) and value.strip() else None


def parsed_day(stamp: str | None) -> date | None:
    try:
        return datetime.fromisoformat(stamp or "").date()
    except ValueError:
        return None


def month_day(stamp: str | None) -> str | None:
    day = parsed_day(stamp)
    return f"{day.strftime('%B')} {day.day}" if day else None


@dataclass(frozen=True)
class Details:
    carrier: str | None
    tracking: str | None
    day: str | None

    @property
    def bare(self) -> bool:
        return self.tracking is None and self.day is None

    @property
    def date_only(self) -> bool:
        return self.carrier is None and self.tracking is None and self.day is not None

    @property
    def full(self) -> bool:
        return None not in (self.carrier, self.tracking, self.day)


def details_of(node: Node) -> Details:
    delivered = field_value(node, "transport_status") == DELIVERED
    stamp = field_value(node, "delivered_at" if delivered else "estimated_delivery")
    return Details(
        field_value(node, "carrier"), field_value(node, "tracking_number"), month_day(stamp)
    )


def clauses_of(copy: ParcelCopy, details: Details, *, delivered: bool) -> list[str]:
    templates = copy.facts["delivered" if delivered else "shipped"]
    given = (("carrier", details.carrier), ("tracking", details.tracking), ("date", details.day))
    return [templates[name].replace(VALUE_SLOT, value) for name, value in given if value]


def missing_name(details: Details, *, delivered: bool) -> str | None:
    if delivered:
        return None
    if details.bare:
        return "both"
    if details.day is None:
        return "date"
    return "tracking" if details.tracking is None else None


def sentence_of(
    copy: ParcelCopy, form: ParcelForm, opening: str, details: Details, *, delivered: bool
) -> str:
    absent = missing_name(details, delivered=delivered)
    facts = clauses_of(copy, details, delivered=delivered)
    tail = copy.missing[absent].replace(FOR_IT_SLOT, form.for_it) if absent else None
    if not facts:
        return f"{opening}, {tail}." if tail else f"{opening}."
    return f"{opening}: {', '.join([*facts, *([tail] if tail else [])])}."


def delivered_on(form: ParcelForm, details: Details, ordinal: str = "") -> str:
    return form.delivered_on.replace(ORDINAL_SLOT, ordinal).replace(VALUE_SLOT, details.day or "")


def several_sentence(copy: ParcelCopy, index: int, node: Node) -> str:
    status = field_value(node, "transport_status") or ""
    details, form = details_of(node), copy.forms[SEVERAL]
    delivered = status == DELIVERED
    ordinal = copy.ordinals[min(index, len(copy.ordinals) - 1)]
    if delivered and details.date_only:
        return delivered_on(form, details, ordinal)
    opening = f"{form.subject.replace(ORDINAL_SLOT, ordinal)} {copy.status[status]}"
    return sentence_of(copy, form, opening, details, delivered=delivered)


def one_sentence(copy: ParcelCopy, opening: str, node: Node) -> str:
    delivered = field_value(node, "transport_status") == DELIVERED
    details, form = details_of(node), copy.forms[ONE]
    if delivered and details.date_only:
        return delivered_on(form, details)
    return sentence_of(copy, form, opening, details, delivered=delivered)
