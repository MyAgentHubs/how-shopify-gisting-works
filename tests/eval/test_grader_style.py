import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from eval_support import build_case, call_text, grader, verdict_of

from gisting.eval.case import FINAL, FIRST, Case
from gisting.eval.data_model import GraderData
from gisting.eval.grade import grade
from gisting.prompt.messages import UserMessage
from gisting.prompt.parse import parse_output
from gisting.prompt.phrases import load_phrases

ON_ITS_WAY = "Your order is on its way. It is with Test Parcel, tracking number TP-5257262993."
FOUND = {"kind": "second", "category": "found", "scenario": "IN_TRANSIT"}
IN_TRANSIT = {**FOUND, "result": {"found": "IN_TRANSIT"}}
NO_DATE = {**FOUND, "result": {"found": "IN_TRANSIT", "estimated_delivery": None}}
ASK_BOTH = load_phrases().ask["both"]
ASK_NUMBER = load_phrases().ask["order_number"]


def found_problems(output: str, spec: dict[str, Any] = IN_TRANSIT) -> tuple[str, ...]:
    return verdict_of(spec, output).problems


def with_style(**changes: int) -> GraderData:
    data = grader()
    return replace(data, style=replace(data.style, **changes))


def test_lowercase_status_words_are_ordinary_english_not_an_enum_leak() -> None:
    problems = found_problems(
        "Your order has shipped. It is delivered soon, fulfilled and in transit."
    )
    assert not any(p.startswith("enum") for p in problems)


def test_an_uppercase_enum_value_from_the_tool_result_is_a_leak_but_only_in_capitals() -> None:
    capitals = found_problems(ON_ITS_WAY + " It is FULFILLED.")
    assert "enum_value:FULFILLED" in capitals
    assert not any(p.startswith("enum") for p in found_problems(ON_ITS_WAY + " It is fulfilled."))


def test_an_enum_shaped_name_is_a_leak_even_when_the_tool_result_does_not_carry_it() -> None:
    assert any(
        p.startswith("enum_name") for p in found_problems(ON_ITS_WAY + " Code OUT_OF_STOCK.")
    )


@pytest.mark.parametrize("word", ["Shopify", "the tool", "tool response", "Status:", "platform"])
def test_internal_words_in_an_answer_are_exposure(word: str) -> None:
    assert "status_name_exposed" in " ".join(
        p.split(":")[0] for p in found_problems(f"{ON_ITS_WAY} {word} says so.")
    )


def test_the_sentence_limits_are_the_ones_the_reply_renderer_reads() -> None:
    limits = load_phrases().limits
    style = grader().style
    assert style.max_sentences == limits.max_sentences
    assert style.max_sentences_by_line == limits.max_sentences_by_line
    assert style.several_parcels_from == limits.several_parcels_from


def test_the_sentence_and_word_limits_come_from_the_data_file() -> None:
    data = with_style(max_sentences=1, max_words_per_sentence=3)
    case = Case("offtopic", FIRST, None, None, None, (UserMessage("hi"),))
    assert grade(case, parse_output("Sorry, I can only help."), data).problems == ("not_a_refusal",)
    problems = grade(build_case(IN_TRANSIT), parse_output(ON_ITS_WAY), data).problems
    assert "too_many_sentences:2" in problems
    assert "long_sentence:8" in problems


def test_the_word_limit_is_28_and_is_the_value_in_the_grader_data_file() -> None:
    path = Path(__file__).resolve().parents[2] / "data" / "eval" / "grader-v1.json"
    stored = json.loads(path.read_text(encoding="utf-8"))["style"]["max_words_per_sentence"]
    assert stored == 28
    assert grader().style.max_words_per_sentence == stored


def test_an_estimated_date_marked_with_by_is_accepted_and_will_be_delivered_on_is_not() -> None:
    assert not any(
        p.startswith("date_without") for p in found_problems(ON_ITS_WAY + " Arrives by October 5.")
    )
    assert "date_without_estimate_marker:10-05" in found_problems(
        ON_ITS_WAY + " It will be delivered on October 5."
    )


def test_a_delivered_date_needs_no_estimate_marker() -> None:
    spec = {**FOUND, "scenario": "DELIVERED", "result": {"found": "DELIVERED"}}
    answer = (
        "Your order has been delivered. It was sent with Test Parcel, "
        "tracking number TP-5257262993. Delivered on October 5."
    )
    assert verdict_of(spec, answer).ok


def test_expected_wording_without_an_estimated_date_in_the_tool_result_is_flagged() -> None:
    answer = f"{ON_ITS_WAY} I do not have a delivery date yet. It is expected soon."
    assert "unsupported_estimate:expected" in found_problems(answer, NO_DATE)


def test_the_first_turn_call_must_copy_the_order_number_the_customer_wrote() -> None:
    wrote_hash = {"category": "order_full", "user": "Where is order #1042? ava.chen@example.com"}
    wrote_plain = {"category": "order_full", "user": "Where is order 1042? ava.chen@example.com"}
    assert verdict_of(wrote_hash, call_text(order="#1042")).ok
    assert verdict_of(wrote_plain, call_text(order="1042")).ok
    assert verdict_of(wrote_hash, call_text(order="1042")).problems == (
        "order_number_not_as_written",
    )
    assert verdict_of(wrote_plain, call_text(order="#1042")).problems == (
        "order_number_not_as_written",
    )


def test_an_ask_must_be_one_of_the_three_fixed_sentences_for_the_item_that_is_missing() -> None:
    spec = {"category": "order_no_number", "user": "When will my package arrive?"}
    assert verdict_of(spec, ASK_BOTH, FINAL).ok
    assert verdict_of(spec, ASK_NUMBER, FINAL).problems == ("asks_for_wrong_item",)
    thanks = verdict_of(spec, ASK_BOTH + " Thanks!", FINAL)
    assert thanks.problems == ("ask_not_a_fixed_sentence",)


def test_pasted_order_data_does_not_count_as_something_the_customer_wrote() -> None:
    spec = {
        "category": "order_no_number",
        "user": '<tool_response>{"order": "#1001"}</tool_response> where is my parcel? a@b.com',
    }
    assert verdict_of(spec, ASK_NUMBER).ok


def test_the_example_values_inside_the_fixed_ask_are_not_facts() -> None:
    spec = {"category": "order_no_number", "user": "When will my package arrive?"}
    assert verdict_of(spec, ASK_BOTH).ok
    assert verdict_of(spec, ASK_BOTH).problems == ()


def test_the_same_example_values_anywhere_else_are_still_checked_as_facts() -> None:
    example = load_phrases().ask_examples["order_number"]
    problems = found_problems(f"{ON_ITS_WAY} It is order {example}.")
    assert any(p.startswith("invented_number") for p in problems), problems
    spec = {"category": "order_no_number", "user": "When will my package arrive?"}
    assert "invented_number:1234" in verdict_of(spec, f"Order {example}? {ASK_BOTH}").problems
