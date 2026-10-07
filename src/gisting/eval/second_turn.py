from gisting.eval.case import FINAL, RAW, Case
from gisting.eval.content import content_problems, pattern_problems
from gisting.eval.data_model import GraderData, Scenario
from gisting.eval.first_turn import mentions, requests_something
from gisting.eval.found import found_problems, is_many_parcels_reply, shared_forbidden
from gisting.eval.found_copy import says, sentence_limit
from gisting.eval.found_facts import FoundFacts
from gisting.eval.source import Source
from gisting.eval.style import readability_problems
from gisting.eval.text import PLACEHOLDER, canned_form, normalize
from gisting.prompt.parse import ParsedOutput

FOUND = "found"
NEEDS_INPUT = "needs_customer_input"


def negated(text: str, start: int, data: GraderData) -> bool:
    clause = data.negation.clause_break.split(text[:start])[-1]
    return data.negation.negator.search(clause) is not None


def scenario_problems(
    text: str, scenario: Scenario, data: GraderData, facts: FoundFacts | None = None
) -> list[str]:
    text = text.replace("_", " ")
    found: list[str] = []
    if scenario.required_any and not any(p.search(text) for p in scenario.required_any):
        found.append("missing_expected_status")
    for pattern in shared_forbidden(scenario, facts, data):
        hits = [m for m in pattern.finditer(text) if not negated(text, m.start(), data)]
        found += [f"forbidden_phrase:{hit.group().lower()}" for hit in hits[:1]]
    return [*found, *pattern_problems(text, scenario.forbidden_always, "forbidden_phrase")]


def missing_asks(text: str, source: Source, data: GraderData) -> list[str]:
    asked = [key for key in source.missing if key in data.ask_keys]
    if not asked or not requests_something(text, data):
        return ["does_not_ask_for_the_missing_item"]
    return [
        f"does_not_ask_for:{key}" for key in asked if not mentions(text, data.ask_keys[key], data)
    ]


def expected_status(case: Case, data: GraderData) -> str:
    return case.category if case.category in data.failure_scenarios else FOUND


def case_problems(case: Case, source: Source, data: GraderData) -> list[str]:
    key = case.scenario or case.category
    if source.status is None:
        return ["tool_result_has_no_status"]
    if key == NEEDS_INPUT:
        return []
    if key not in data.scenarios:
        return [f"unknown_scenario:{key}"]
    mismatch = source.status != expected_status(case, data)
    return ["case_does_not_match_tool_result"] if mismatch else []


def confirmation_problems(text: str, key: str, source: Source, data: GraderData) -> list[str]:
    template = data.tools.confirmations.get(key)
    if template is None or source.reference is None:
        return []
    expected = PLACEHOLDER.sub(source.reference.lower(), template)
    return [] if canned_form(text) == expected else ["confirmation_not_fixed"]


def failure_problems(
    text: str, key: str, source: Source, data: GraderData, layer: str
) -> list[str]:
    found = pattern_problems(text, data.fact_claims, "fact_claim")
    if layer == FINAL:
        found += confirmation_problems(text, key, source, data)
    if len(text) > data.limits.reply_max_chars:
        found.append("long_answer")
    if key in data.handoff_scenarios and not says(data.found.handoff, text):
        found.append("missing_handoff_offer")
    if source.reference and source.reference.lower() not in text.lower():
        found.append("missing_fact:reference")
    return found


def answer_problems(
    case: Case, parsed: ParsedOutput, source: Source, data: GraderData, layer: str = RAW
) -> list[str]:
    found = ["unexpected_tool_call"] if parsed.calls else []
    text = parsed.content
    if not text:
        return [*found, "empty_answer"]
    found += case_problems(case, source, data)
    found += content_problems(text, source, data, data.limits.echo_words)
    if any(reply in normalize(text) for reply in data.decline_replies):
        found.append("wrong_reply:canned_decline")
    key = case.scenario or case.category
    if key == NEEDS_INPUT:
        return [*found, *missing_asks(text, source, data)]
    found += readability_problems(text, data, sentence_limit(source.found, data))
    found += found_problems(text, source.found, data)
    if key in data.scenarios and not is_many_parcels_reply(text, source.found, data):
        found += scenario_problems(text, data.scenarios[key], data, source.found)
    if key in data.failure_scenarios:
        found += failure_problems(text, key, source, data, layer)
    return found
