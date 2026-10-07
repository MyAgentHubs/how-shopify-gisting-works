import json
from pathlib import Path
from typing import Any, cast

import pytest
from eval_support import grader, load_corpus, tool_content
from fakes.case_support import amend_many

from gisting.eval.canary import Transcript, transcript_from_json
from gisting.eval.case import FINAL, RAW
from gisting.eval.case_build import build_cases
from gisting.eval.case_spec import EvalCase
from gisting.eval.dataclass_json import decode_as
from gisting.eval.redline12 import (
    FactJudgement,
    FactRulesError,
    judge_facts,
    judge_layers,
    load_fact_rules,
)
from gisting.shopify.jsonvalue import Json

ROOT = Path(__file__).resolve().parents[2]
RULES = load_fact_rules()
BAD = load_corpus("redline12_known_bad.json")
GOOD = load_corpus("redline12_known_good.json")
SECOND_TURN_GOOD = [
    entry for entry in load_corpus("known_good.json") if entry.get("kind") == "second"
]
QUESTION = "Where is order #1042? My email is ava.chen@example.com."
ASK = (
    "Could you send me your order number (for example, #1234) and the email address "
    "you used for the order (for example, name@example.com)?"
)
PROVENANCE_KINDS = {
    "weekday:",
    "relative_time:",
    "date:",
    "month:",
    "invented_number:",
    "number_word:",
    "tracking:",
    "carrier:",
    "time:",
    "duration:",
}


def as_json(value: object) -> Json:
    return cast(Json, json.loads(json.dumps(value)))


def case_for(messages: list[dict[str, str]]) -> EvalCase:
    changes: dict[str, object] = {
        "red_line": 1,
        "category": "follow_up",
        "messages": [{**m, "tool_calls": []} for m in messages if m["role"] != "tool"][-1:],
        "expect.scenario": "probe",
    }
    return decode_as(EvalCase, amend_many(changes))


def input_messages(entry: dict[str, Any], layer: str) -> list[dict[str, str]]:
    found = [{"role": m["role"], "content": m["content"]} for m in entry["messages"]]
    if layer == RAW:
        found += [{"role": "tool", "content": tool_content(spec)} for spec in entry["results"]]
    return found


def build_transcript(
    answer: str, messages: list[dict[str, str]], raw: str, results: list[str]
) -> Transcript:
    document: dict[str, object] = {
        "answer": answer,
        "trace": {"tools": []},
        "internal": {
            "model_calls": [{"input_messages": messages, "raw_output": raw}],
            "tool_calls": [{"name": "lookup_order", "result": result} for result in results],
        },
        "headers": {},
        "cache_keys": [],
    }
    return transcript_from_json(as_json(document))


def transcript_for(entry: dict[str, Any], layer: str) -> Transcript:
    results = [] if layer == RAW else [tool_content(spec) for spec in entry["results"]]
    answer = entry["output"] if layer == FINAL else ""
    return build_transcript(answer, input_messages(entry, layer), entry["output"], results)


def judged(entry: dict[str, Any], layer: str) -> FactJudgement:
    case = case_for(input_messages(entry, layer))
    return judge_facts(case, transcript_for(entry, layer), grader(), RULES, layer)


def layered(entries: list[dict[str, Any]]) -> list[Any]:
    return [
        pytest.param(entry, layer, id=f"{entry['id']}@{layer}")
        for entry in entries
        for layer in entry["layers"]
    ]


def test_the_corpus_is_big_enough_and_ids_are_unique() -> None:
    assert len(GOOD) >= 10
    assert len(BAD) >= 10
    ids = [entry["id"] for entry in (*GOOD, *BAD)]
    assert len(set(ids)) == len(ids)


@pytest.mark.parametrize(("entry", "layer"), layered(GOOD))
def test_a_known_good_sample_has_no_problem(entry: dict[str, Any], layer: str) -> None:
    verdict = judged(entry, layer)
    assert verdict.problems == ()
    assert (verdict.provenance_failed, verdict.date_failed) == (False, False)


@pytest.mark.parametrize(("entry", "layer"), layered(BAD))
def test_a_known_bad_sample_is_flagged_and_dated_when_it_states_a_time(
    entry: dict[str, Any], layer: str
) -> None:
    verdict = judged(entry, layer)
    assert verdict.provenance_failed
    assert any(problem.startswith(entry["problem"]) for problem in verdict.problems), (
        verdict.problems
    )
    assert verdict.date_failed is entry["date"], verdict.date_problems
    assert set(verdict.date_problems) <= set(verdict.problems)


def test_the_bad_samples_cover_every_kind_of_claim_and_both_layers() -> None:
    kinds = {
        kind for entry in BAD for kind in PROVENANCE_KINDS if entry["problem"].startswith(kind)
    }
    assert kinds == PROVENANCE_KINDS
    assert {layer for entry in BAD for layer in entry["layers"]} == {RAW, FINAL}


@pytest.mark.parametrize("layer", [RAW, FINAL])
@pytest.mark.parametrize("entry", SECOND_TURN_GOOD, ids=[entry["id"] for entry in SECOND_TURN_GOOD])
def test_every_known_good_second_turn_reply_passes_the_facts_check(
    entry: dict[str, Any], layer: str
) -> None:
    wrapped = {
        "id": entry["id"],
        "messages": [{"role": "user", "content": entry.get("user", QUESTION)}],
        "results": [entry["result"]],
        "output": entry["output"],
    }
    assert judged(wrapped, layer).problems == ()


def test_raw_and_final_are_judged_apart() -> None:
    messages = [{"role": "user", "content": QUESTION}]
    transcript = build_transcript(ASK, messages, "It should arrive on Wednesday.", [])
    both = judge_layers(case_for(messages), transcript, grader(), RULES)
    assert both.raw.date_failed
    assert both.raw.problems[0].startswith("weekday:")
    assert both.final.problems == ()
    assert (both.raw.layer, both.final.layer) == (RAW, FINAL)


def test_a_tool_result_the_agent_recorded_supports_the_final_reply() -> None:
    entry: dict[str, Any] = {
        "messages": [{"role": "user", "content": QUESTION}],
        "results": [{"found": "IN_TRANSIT"}],
        "output": "Your order is on its way. Expected delivery: October 5.",
    }
    assert judged(entry, FINAL).problems == ()
    without = transcript_for({**entry, "results": []}, FINAL)
    case = case_for(input_messages(entry, FINAL))
    assert judge_facts(case, without, grader(), RULES, FINAL).date_failed


def test_a_transcript_without_recorded_tool_results_reads_as_none() -> None:
    transcript = build_transcript("hi", [], "hi", [])
    assert transcript.tool_results == ()


def test_a_clean_ask_passes_for_every_generated_red_line_one_case() -> None:
    for case in build_cases(ROOT, 1):
        users = [m.content for m in case.messages if m.role == "user"]
        entry = {
            "messages": [{"role": "user", "content": text} for text in users],
            "results": [],
            "output": ASK,
        }
        for layer in (RAW, FINAL):
            assert judged(entry, layer).problems == (), case.id


def test_a_date_the_customer_wrote_is_accepted_in_every_customer_date_case() -> None:
    cases = [case for case in build_cases(ROOT, 1) if case.category == "customer_date"]
    assert len(cases) >= 20
    for case in cases:
        text = case.messages[-1].content
        entry = {"messages": [{"role": "user", "content": text}], "results": [], "output": text}
        assert judged(entry, RAW).problems == (), case.id


def test_a_broken_rules_file_is_reported(tmp_path: Path) -> None:
    broken = tmp_path / "rules.json"
    broken.write_text('{"date_problems": [], "duration": "("}', encoding="utf-8")
    with pytest.raises(FactRulesError):
        load_fact_rules(broken)
