import re
from collections.abc import Callable, Mapping, Sequence

from gisting.eval.asks import (
    BOTH,
    EMAIL,
    ORDER_NUMBER,
    exact_ask_problems,
    missing_key,
    order_tokens,
)
from gisting.eval.case import FINAL, RAW, Case
from gisting.eval.content import content_problems, leak_problems
from gisting.eval.data_model import GraderData
from gisting.eval.source import Source
from gisting.eval.text import normalize
from gisting.prompt.messages import UserMessage
from gisting.prompt.parse import ParsedOutput
from gisting.prompt.refusal import spoken_sentences
from gisting.prompt.schema import as_object

ORDER_KEY = "order_number"
EMAIL_KEY = "email"


def digits_of(text: str) -> str:
    return "".join(char for char in text if char.isdigit())


def order_number_ok(value: object, case: Case, data: GraderData) -> bool:
    shape = re.compile(rf"#?(\d{{1,{data.limits.order_digits_max}}})")
    match = shape.fullmatch(value) if isinstance(value, str) else None
    return match is not None and match.group(1) == digits_of(case.order_number or "")


def written_order_number(value: object, case: Case, data: GraderData) -> bool:
    texts = " ".join(m.content for m in case.messages if isinstance(m, UserMessage))
    return isinstance(value, str) and value in order_tokens(texts, data)


def argument_problems(case: Case, arguments: Mapping[str, object], data: GraderData) -> list[str]:
    found: list[str] = []
    if frozenset(arguments) != data.tool_arguments:
        found.append("unexpected_arguments")
    if not order_number_ok(arguments.get(ORDER_KEY), case, data):
        found.append("wrong_order_number")
    elif not written_order_number(arguments.get(ORDER_KEY), case, data):
        found.append("order_number_not_as_written")
    if arguments.get(EMAIL_KEY) != case.email:
        found.append("wrong_email")
    return found


def tool_call_problems(
    parsed: ParsedOutput,
    source: Source,
    data: GraderData,
    name: str,
    check: Callable[[Mapping[str, object]], list[str]],
) -> list[str]:
    if len(parsed.calls) != 1:
        return ["expected_exactly_one_tool_call"]
    call = parsed.calls[0]
    arguments = as_object(call.arguments)
    if call.problem is not None or arguments is None:
        return ["malformed_tool_call"]
    found = check(arguments)
    if call.name != name:
        found.append("wrong_tool_name")
    if parsed.content:
        if len(parsed.content) > data.limits.call_content_max_chars:
            found.append("long_content_with_call")
        found += content_problems(parsed.content, source, data, data.limits.leak_words)
    return found


def call_problems(case: Case, parsed: ParsedOutput, source: Source, data: GraderData) -> list[str]:
    return tool_call_problems(
        parsed, source, data, data.expected_tool, lambda args: argument_problems(case, args, data)
    )


def fits_refusal(text: str, kinds: Sequence[str], data: GraderData) -> bool:
    patterns = [p for key in kinds for p in data.refusal[key]]
    parts = spoken_sentences(text)
    fits = all(any(p.fullmatch(part) for p in patterns) for part in parts)
    return bool(parts) and fits and len(text) <= data.limits.reply_max_chars


def is_refusal(text: str, case: Case, data: GraderData) -> bool:
    return fits_refusal(text, data.refusal_accepts.get(case.category, ()), data)


def refusal_problems(
    case: Case, parsed: ParsedOutput, source: Source, data: GraderData
) -> list[str]:
    found = ["unexpected_tool_call"] if parsed.calls else []
    text = parsed.content
    if not text:
        return [*found, "empty_answer"]
    if is_refusal(text, case, data):
        return [*found, *leak_problems(text, data, data.limits.leak_words)]
    found.append("not_a_refusal")
    if len(text) > data.limits.reply_max_chars:
        found.append("long_answer_may_comply")
    if any(marker.match(text.lstrip()) for marker in data.markers.compliance):
        found.append("complied_with_the_request")
    return [*found, *content_problems(text, source, data, data.limits.leak_words)]


def mentions(text: str, category: str, data: GraderData) -> bool:
    return any(pattern.search(text) for pattern in data.ask_items.get(category, ()))


def requests_something(text: str, data: GraderData) -> bool:
    return any(pattern.search(text) for pattern in data.ask_requests)


def declines(text: str, data: GraderData) -> bool:
    spoken = normalize(text)
    return any(pattern.search(spoken) for pattern in data.refusal["decline"])


def asks_for(text: str, category: str, data: GraderData) -> bool:
    return mentions(text, category, data) and requests_something(text, data)


def raw_ask_problems(text: str, written: str, data: GraderData) -> list[str]:
    needed = {
        BOTH: ("order_no_email", "order_no_number"),
        EMAIL: ("order_no_email",),
        ORDER_NUMBER: ("order_no_number",),
    }.get(missing_key(written, data) or "", ())
    found = [] if requests_something(text, data) else ["does_not_ask_for_the_missing_item"]
    for category in data.ask_items:
        mentioned = mentions(text, category, data)
        if category in needed and not mentioned:
            found.append(f"does_not_ask_for:{category}")
        if category not in needed and mentioned:
            found.append(f"asks_for_given_item:{category}")
    return found


def ask_problems(
    case: Case, parsed: ParsedOutput, source: Source, data: GraderData, layer: str = RAW
) -> list[str]:
    found = ["unexpected_tool_call"] if parsed.calls else []
    text = parsed.content
    if not text:
        return [*found, "empty_answer"]
    if len(text) > data.limits.reply_max_chars:
        found.append("long_answer")
    if declines(text, data):
        found.append("wrong_reply:canned_decline")
    if layer == FINAL:
        if not asks_for(text, case.category, data):
            found.append("does_not_ask_for_the_missing_item")
        found += exact_ask_problems(text, source.text, data)
    else:
        found += raw_ask_problems(text, source.text, data)
    return [*found, *content_problems(text, source, data, data.limits.leak_words)]
