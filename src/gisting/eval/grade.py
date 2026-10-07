from collections.abc import Callable
from dataclasses import replace

from gisting.eval.case import DECISION, FIRST, RAW, SECOND, Case, Verdict
from gisting.eval.data_model import GraderData
from gisting.eval.first_turn import ask_problems, call_problems, refusal_problems
from gisting.eval.first_turn_tools import (
    handoff_call_problems,
    no_call_problems,
    reminder_call_problems,
)
from gisting.eval.policy_call import search_call_problems
from gisting.eval.second_turn import answer_problems
from gisting.eval.source import Source, build_source
from gisting.prompt.parse import ParsedOutput

CALL = "call"
ASK = "ask"
REFUSE = "refuse"
HANDOFF = "handoff"
PRIORITY = "reminder"
NO_CALL = "no_call"
SEARCH = "search"
NO_DECISION = "second_turn_has_no_decision"


def first_turn_problems(
    case: Case, parsed: ParsedOutput, source: Source, data: GraderData, layer: str
) -> list[str]:
    handlers: dict[str, Callable[[], list[str]]] = {
        CALL: lambda: call_problems(case, parsed, source, data),
        ASK: lambda: ask_problems(case, parsed, source, data, layer),
        REFUSE: lambda: refusal_problems(case, parsed, source, data),
        HANDOFF: lambda: handoff_call_problems(case, parsed, source, data),
        PRIORITY: lambda: reminder_call_problems(case, parsed, source, data),
        NO_CALL: lambda: no_call_problems(parsed, source, data),
        SEARCH: lambda: search_call_problems(case, parsed, source, data),
    }
    handler = handlers.get(data.first_turn.get(case.category, ""))
    return handler() if handler else [f"unknown_category:{case.category}"]


def problems_of(case: Case, parsed: ParsedOutput, data: GraderData, layer: str = RAW) -> list[str]:
    source = replace(build_source(case, data), layer=layer)
    if case.kind == SECOND:
        return (
            [NO_DECISION]
            if layer == DECISION
            else answer_problems(case, parsed, source, data, layer)
        )
    if case.kind != FIRST:
        return [f"unknown_kind:{case.kind}"]
    return first_turn_problems(case, parsed, source, data, layer)


def grade(case: Case, parsed: ParsedOutput, data: GraderData, layer: str = RAW) -> Verdict:
    problems = tuple(dict.fromkeys(problems_of(case, parsed, data, layer)))
    return Verdict(not problems, problems)
