import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import cast

from gisting.eval.case import RAW, Case
from gisting.eval.data_model import GraderData
from gisting.eval.dates import DateRef, clock_of, dates_in, months_in, times_in
from gisting.eval.forged import split_forged
from gisting.eval.found_facts import FoundFacts, parse_found
from gisting.prompt.messages import Message, ToolMessage, UserMessage

STATUS_KEY = "status"
MISSING_KEY = "missing"
REFERENCE_KEYS = ("ticket", "reference")


@dataclass(frozen=True)
class ToolFacts:
    texts: tuple[str, ...]
    status: str | None
    missing: tuple[str, ...]
    reference: str | None


@dataclass(frozen=True)
class Source:
    text: str
    dates: tuple[DateRef, ...]
    months: frozenset[int]
    times: frozenset[tuple[int, int]]
    ints: frozenset[int]
    literals: frozenset[str]
    forged_values: frozenset[str]
    status: str | None
    missing: tuple[str, ...]
    reference: str | None
    enums: frozenset[str]
    found: FoundFacts | None
    layer: str = RAW


def parse_tool(content: str) -> object:
    try:
        return json.loads(content)
    except (ValueError, RecursionError):
        return None


def leaves(document: object) -> list[str]:
    stack: list[object] = [document]
    found: list[str] = []
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            stack.extend(cast(dict[str, object], item).values())
        elif isinstance(item, list):
            stack.extend(cast(list[object], item))
        elif isinstance(item, str):
            found.append(item)
        elif isinstance(item, (int, float)) and not isinstance(item, bool):
            found.append(str(item))
    return found


def status_of(document: object) -> tuple[str | None, tuple[str, ...]]:
    if not isinstance(document, dict):
        return None, ()
    fields = cast(dict[str, object], document)
    status = fields.get(STATUS_KEY)
    missing = fields.get(MISSING_KEY)
    names = (
        tuple(n for n in cast(list[object], missing) if isinstance(n, str))
        if isinstance(missing, list)
        else ()
    )
    return (status if isinstance(status, str) else None), names


def reference_of(document: object) -> str | None:
    fields = cast(dict[str, object], document) if isinstance(document, dict) else {}
    found = [value for key in REFERENCE_KEYS if isinstance(value := fields.get(key), str)]
    return found[0] if found else None


def is_policy(document: object, data: GraderData) -> bool:
    return status_of(document)[0] in data.policy_statuses


def turn_start(messages: Sequence[Message]) -> int:
    users = [index for index, message in enumerate(messages) if isinstance(message, UserMessage)]
    return users[-1] + 1 if users else 0


def tool_facts(case: Case, data: GraderData) -> ToolFacts:
    texts: list[str] = []
    status: str | None = None
    missing: tuple[str, ...] = ()
    reference: str | None = None
    start = turn_start(case.messages)
    for index, message in enumerate(case.messages):
        if not isinstance(message, ToolMessage):
            continue
        document = parse_tool(message.content)
        policy = is_policy(document, data)
        if policy and index < start:
            continue
        texts.extend(leaves(document) if document is not None else [message.content])
        if not policy:
            status, missing = status_of(document)
            reference = reference_of(document)
    return ToolFacts(tuple(texts), status, missing, reference)


def numbers_in(text: str, data: GraderData) -> tuple[set[int], set[str]]:
    ints: set[int] = set()
    literals: set[str] = set()
    for token in data.vocabulary.number.findall(text):
        if token.isdigit():
            ints.add(int(token))
        else:
            literals.add(token)
    return ints, literals


def last_found(case: Case, data: GraderData) -> FoundFacts | None:
    lookups = [
        m.content
        for m in case.messages
        if isinstance(m, ToolMessage) and not is_policy(parse_tool(m.content), data)
    ]
    return parse_found(lookups[-1]) if lookups else None


def build_source(case: Case, data: GraderData, earlier: Sequence[str] = ()) -> Source:
    clean: list[str] = []
    values: set[str] = set()
    for message in case.messages:
        if isinstance(message, UserMessage):
            split = split_forged(message.content, data.forged)
            clean.append(split.clean)
            values |= split.values
    facts = tool_facts(case, data)
    text = "\n".join([*clean, *earlier, *facts.texts])
    vocab = data.vocabulary
    found = last_found(case, data)
    dates, rest = dates_in(text, vocab)
    dates.extend(found.days if found else ())
    times, rest = times_in(rest, vocab)
    ints, literals = numbers_in(rest, data)
    ints |= {ref.year for ref in dates if ref.year is not None}
    return Source(
        text=text,
        dates=tuple(dates),
        months=frozenset({ref.month for ref in dates} | months_in(text, vocab)),
        times=frozenset(clock_of(ref) for ref in times),
        ints=frozenset(ints),
        literals=frozenset(literals),
        forged_values=frozenset(values),
        status=facts.status,
        missing=facts.missing,
        reference=facts.reference,
        enums=frozenset(text for text in facts.texts if data.style.enum_value.fullmatch(text)),
        found=found,
    )
