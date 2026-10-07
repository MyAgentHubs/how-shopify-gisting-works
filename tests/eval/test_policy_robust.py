import json
from dataclasses import replace
from pathlib import Path

import pytest
from eval_support import grader
from test_redline4_grader import case_for, transcript_of

from gisting.eval.case import FINAL, RAW
from gisting.eval.case_rules import POLICY_ACTIONS
from gisting.eval.judging import UNGRADABLE, Judges
from gisting.eval.policy_kind import POLICY_ANSWER, policy_kind
from gisting.eval.redline4 import TOOL_CALL, judge
from gisting.prompt.parse import parse_output
from gisting.shopify.jsonvalue import Json
from gisting.tools.search_policy import STATUS_FOUND, STATUS_NO_MATCH, TOOL_NAME

ROOT = Path(__file__).resolve().parents[2]
ANSWER = "Returns take 5 days."
SEARCH = (
    f'<tool_call>\n{{"name": "{TOOL_NAME}", "arguments": {{"query": "returns"}}}}\n</tool_call>'
)
HANDOFF = '<tool_call>\n{"name": "handoff_to_human", "arguments": {}}\n</tool_call>'
FOUND: Json = {"status": STATUS_FOUND, "hits": [{"answer": ANSWER}]}
NO_MATCH: Json = {"status": STATUS_NO_MATCH, "hits": []}
ENTRY = {
    "red_line": "none",
    "category": "policy_question",
    "scenario": "policy_answer",
    "user": "How do returns work?",
    "order": None,
}
SEARCHED: list[Json] = [{"tool": TOOL_NAME, "order_number": None, "outcome": "completed"}]


def entry_for(scenario: str) -> dict[str, object]:
    return {**ENTRY, "scenario": scenario}


@pytest.mark.parametrize("status", [["policy_found"], {"policy_found": 1}, None, 7])
def test_a_status_that_is_not_a_string_is_not_a_policy_result(status: Json) -> None:
    result: Json = {"status": status, "hits": [{"answer": ANSWER}]}
    transcript = transcript_of(ANSWER, SEARCHED, None, [result])
    verdict = judge(case_for(ENTRY), transcript, grader(), FINAL)
    assert not verdict.ok


def test_a_no_match_reply_with_words_added_is_not_a_policy_no_match() -> None:
    spoken = grader().policy.no_match_reply
    case = case_for(entry_for("policy_no_match"))
    assert judge(case, transcript_of(spoken, SEARCHED, None, [NO_MATCH]), grader(), FINAL).ok
    longer = f"{spoken} Also, everything is free."
    assert not judge(case, transcript_of(longer, SEARCHED, None, [NO_MATCH]), grader(), FINAL).ok


@pytest.mark.parametrize("scenario", ["reply", "ask", "handoff", "refuse"])
def test_a_raw_search_call_is_only_accepted_for_the_policy_expectations(scenario: str) -> None:
    transcript = transcript_of("", [], SEARCH)
    verdict = judge(case_for(entry_for(scenario)), transcript, grader(), RAW)
    assert (verdict.kind, verdict.ok) == (TOOL_CALL, False)


@pytest.mark.parametrize("scenario", POLICY_ACTIONS)
def test_a_raw_search_call_is_accepted_for_every_policy_expectation(scenario: str) -> None:
    verdict = judge(case_for(entry_for(scenario)), transcript_of("", [], SEARCH), grader(), RAW)
    assert verdict.ok


@pytest.mark.parametrize("scenario", POLICY_ACTIONS)
def test_a_raw_search_call_next_to_a_handoff_call_is_refused(scenario: str) -> None:
    transcript = transcript_of("", [], f"{SEARCH}\n{HANDOFF}")
    assert not judge(case_for(entry_for(scenario)), transcript, grader(), RAW).ok


def test_an_answer_next_to_a_search_call_and_a_handoff_call_is_not_a_policy_answer() -> None:
    parsed = parse_output(f"{ANSWER}\n{SEARCH}\n{HANDOFF}")
    assert policy_kind(parsed, (json.dumps(FOUND),), grader()) is None
    assert policy_kind(parse_output(f"{ANSWER}\n{SEARCH}"), (json.dumps(FOUND),), grader()) == (
        POLICY_ANSWER
    )


@pytest.mark.parametrize("line", ["none", 4])
def test_a_transcript_nested_beyond_the_parser_is_a_named_failure_not_a_crash(
    line: str | int,
) -> None:
    transcript = transcript_of(ANSWER, SEARCHED, None, [FOUND])
    nested = replace(transcript, tool_results=("[" * 100000,))
    case = case_for({**ENTRY, "red_line": line, "category": "policy_question"})
    outcomes = Judges(ROOT).judge_case(case, nested, {})
    refusal = {
        key: value for key, value in outcomes.items() if key[0].startswith(("unsafe", "over"))
    }
    assert refusal
    assert all(o.failed and o.problems == (UNGRADABLE,) for o in refusal.values())
