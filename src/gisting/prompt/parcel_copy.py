from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import cast

from gisting.prompt.schema import as_object

SHIPPED = "FULFILLED"
ORDINAL_SLOT = "{ordinal}"
VALUE_SLOT = "{value}"
FOR_IT_SLOT = "{for_it}"
SEVERAL = "several"
ONE = "one"
FORMS = (SEVERAL, ONE)
FACT_KINDS = ("shipped", "delivered")
FACT_NAMES = ("carrier", "tracking", "date")
MISSING_NAMES = ("date", "tracking", "both")


class ParcelCopyError(ValueError):
    pass


@dataclass(frozen=True)
class ReplyLimits:
    max_sentences: int
    max_sentences_by_line: dict[str, int]
    several_parcels_from: int
    several_parcels_from_by_line: dict[str, int]
    max_parcels: int

    def parcels_from(self, line: str) -> int:
        return self.several_parcels_from_by_line.get(line, self.several_parcels_from)

    def sentence_limit(self, lines: Iterable[str]) -> int:
        allowed = self.max_sentences_by_line
        return max([self.max_sentences, *(allowed.get(name, 0) for name in lines)])


@dataclass(frozen=True)
class ParcelForm:
    subject: str
    for_it: str
    delivered_on: str


@dataclass(frozen=True)
class ParcelCopy:
    status: dict[str, str]
    facts: dict[str, dict[str, str]]
    missing: dict[str, str]
    forms: dict[str, ParcelForm]
    ordinals: tuple[str, ...]
    closing_order: tuple[str, ...]
    closing_when: dict[str, tuple[str, ...]]
    closing_when_one: dict[str, tuple[str, ...]]
    many_reply: str


def node_at(document: Mapping[str, object], key: str) -> dict[str, object]:
    node = as_object(document.get(key))
    if not node:
        message = f"{key} must be a non-empty object"
        raise ParcelCopyError(message)
    return dict(node)


def names_at(node: Mapping[str, object], key: str) -> tuple[str, ...]:
    value = node.get(key)
    items = cast(list[object], value) if isinstance(value, list) else []
    if not items or not all(isinstance(item, str) and item for item in items):
        message = f"{key} must be a non-empty list of strings"
        raise ParcelCopyError(message)
    return tuple(str(item) for item in items)


def count_at(node: Mapping[str, object], key: str) -> int:
    value = node.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        message = f"{key} must be a positive whole number"
        raise ParcelCopyError(message)
    return value


def parse_limits(document: Mapping[str, object]) -> ReplyLimits:
    node = node_at(document, "limits")
    by_line = node_at(node, "max_sentences_by_line")
    parcels_by_line = node_at(node, "several_parcels_from_by_line")
    return ReplyLimits(
        max_sentences=count_at(node, "max_sentences"),
        max_sentences_by_line={name: count_at(by_line, name) for name in by_line},
        several_parcels_from=count_at(node, "several_parcels_from"),
        several_parcels_from_by_line={
            name: count_at(parcels_by_line, name) for name in parcels_by_line
        },
        max_parcels=count_at(node, "max_parcels"),
    )


def parse_closing(
    document: Mapping[str, object], sentences: Mapping[str, str]
) -> tuple[tuple[str, ...], dict[str, tuple[str, ...]], dict[str, tuple[str, ...]]]:
    node = node_at(document, "parcel_closing")
    order, when, extra = (
        names_at(node, "order"),
        node_at(node, "when"),
        node_at(node, "also_without_tracking"),
    )
    chosen = {status: names_at(when, status) for status in when}
    also = {status: names_at(extra, status) for status in extra}
    named = {name for names in (*chosen.values(), *also.values()) for name in names}
    if not named <= set(order) or not set(order) <= sentences.keys():
        message = "parcel_closing must name only fixed sentences, each listed in its order"
        raise ParcelCopyError(message)
    merged = {
        status: tuple(dict.fromkeys([*chosen.get(status, ()), *also.get(status, ())]))
        for status in (*chosen, *also)
    }
    return order, chosen, merged


def texts_at(
    node: Mapping[str, object], key: str, names: Iterable[str], slot: str | None = None
) -> dict[str, str]:
    texts = node_at(node, key)
    wanted = set(names)
    if texts.keys() != wanted or not all(
        isinstance(text, str) and text.strip() and (slot is None or slot in text)
        for text in texts.values()
    ):
        message = f"{key} needs exactly {sorted(wanted)} as non-empty strings"
        raise ParcelCopyError(message)
    return {name: str(text) for name, text in texts.items()}


def parse_forms(document: Mapping[str, object]) -> dict[str, ParcelForm]:
    node = node_at(document, "parcel_forms")
    forms: dict[str, ParcelForm] = {}
    for name in FORMS:
        item = node_at(node, name)
        subject, for_it = item.get("subject"), item.get("for_it")
        delivered_on = item.get("delivered_on")
        if (
            not isinstance(subject, str)
            or not subject.strip()
            or not isinstance(for_it, str)
            or not isinstance(delivered_on, str)
            or VALUE_SLOT not in delivered_on
        ):
            message = (
                f"parcel_forms.{name} needs a subject, a for_it string and a delivered_on text"
            )
            raise ParcelCopyError(message)
        forms[name] = ParcelForm(subject, for_it, delivered_on)
    several = forms[SEVERAL]
    ordinal_texts = (several.subject, several.delivered_on)
    if node.keys() != set(FORMS) or not all(ORDINAL_SLOT in text for text in ordinal_texts):
        message = "parcel_forms needs several (with an ordinal slot) and one"
        raise ParcelCopyError(message)
    return forms


def parse_facts(document: Mapping[str, object]) -> dict[str, dict[str, str]]:
    node = node_at(document, "parcel_facts")
    if node.keys() != set(FACT_KINDS):
        message = f"parcel_facts needs exactly {sorted(FACT_KINDS)}"
        raise ParcelCopyError(message)
    return {kind: texts_at(node, kind, FACT_NAMES, VALUE_SLOT) for kind in FACT_KINDS}


def parse_parcels(
    document: Mapping[str, object],
    sentences: Mapping[str, str],
    transports: Iterable[str],
    limits: ReplyLimits,
) -> ParcelCopy:
    ordinals = names_at(document, "ordinals")
    if limits.max_parcels > len(ordinals):
        message = "ordinals must cover max_parcels"
        raise ParcelCopyError(message)
    order, when, when_one = parse_closing(document, sentences)
    template = document.get("many_parcels_reply")
    if not isinstance(template, str) or not template.strip():
        message = "many_parcels_reply must be a non-empty string"
        raise ParcelCopyError(message)
    return ParcelCopy(
        status=texts_at(document, "parcel_status", transports),
        facts=parse_facts(document),
        missing=texts_at(document, "parcel_missing", MISSING_NAMES, FOR_IT_SLOT),
        forms=parse_forms(document),
        ordinals=ordinals,
        closing_order=order,
        closing_when=when,
        closing_when_one=when_one,
        many_reply=template.format(**sentences),
    )
