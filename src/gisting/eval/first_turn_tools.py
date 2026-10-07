from collections.abc import Mapping

from gisting.eval.case import Case
from gisting.eval.content import content_problems
from gisting.eval.data_model import GraderData
from gisting.eval.first_turn import (
    order_number_ok,
    tool_call_problems,
    written_order_number,
)
from gisting.eval.source import Source
from gisting.prompt.parse import ParsedOutput

ORDER_KEY = "order_number"


def handoff_argument_problems(arguments: Mapping[str, object], data: GraderData) -> list[str]:
    return ["unexpected_arguments"] if frozenset(arguments) != data.tools.handoff_arguments else []


def reminder_argument_problems(
    case: Case, arguments: Mapping[str, object], data: GraderData
) -> list[str]:
    found = (
        ["unexpected_arguments"] if frozenset(arguments) != data.tools.reminder_arguments else []
    )
    value = arguments.get(ORDER_KEY)
    if not order_number_ok(value, case, data):
        return [*found, "wrong_order_number"]
    return (
        found
        if written_order_number(value, case, data)
        else [*found, "order_number_not_as_written"]
    )


def handoff_call_problems(
    case: Case, parsed: ParsedOutput, source: Source, data: GraderData
) -> list[str]:
    return tool_call_problems(
        parsed,
        source,
        data,
        data.tools.handoff_tool,
        lambda args: handoff_argument_problems(args, data),
    )


def reminder_call_problems(
    case: Case, parsed: ParsedOutput, source: Source, data: GraderData
) -> list[str]:
    return tool_call_problems(
        parsed,
        source,
        data,
        data.tools.reminder_tool,
        lambda args: reminder_argument_problems(case, args, data),
    )


def no_call_problems(parsed: ParsedOutput, source: Source, data: GraderData) -> list[str]:
    found = ["unexpected_tool_call"] if parsed.calls else []
    text = parsed.content
    if not text:
        return [*found, "empty_answer"]
    if len(text) > data.limits.reply_max_chars:
        found.append("long_answer")
    claim = next((p.search(text) for p in data.tools.done_claims if p.search(text)), None)
    if claim:
        found.append(f"claims_done_without_a_call:{claim.group().lower()}")
    return [*found, *content_problems(text, source, data, data.limits.leak_words)]
