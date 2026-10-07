import json

import pytest

from gisting.eval.case import Verdict
from gisting.prompt.parse import ParsedOutput, parse_output
from gisting.shopify.jsonvalue import Json, JsonObject
from gisting.training.metrics import (
    Outcome,
    call_signature,
    mode_metrics,
    percentile,
    prefix_ratio,
    token_f1,
)

TOKENS = {"rules": 240, "tools": 208, "history": 13, "tool_results": 0, "total": 461}
BODY = {"name": "lookup_order", "arguments": {"order_number": "#1", "email": "a@b.c"}}
CALL = "<tool_call>\n" + json.dumps(BODY) + "\n</tool_call>"
OTHER = CALL.replace("#1", "#2")


def at(node: JsonObject, *path: str) -> Json:
    current: Json = node
    for key in path:
        assert isinstance(current, dict)
        current = current[key]
    return current


def outcome(
    text: str,
    kind: str = "first",
    category: str = "order_full",
    ok: bool = True,
    ids: tuple[int, ...] = (1, 2),
) -> Outcome:
    parsed: ParsedOutput = parse_output(text)
    return Outcome("s", kind, category, text, ids, parsed, Verdict(ok, ()), TOKENS, 100.0, 200.0)


def test_percentile_interpolates_and_handles_empty_input() -> None:
    assert percentile([1.0, 2.0, 3.0, 4.0], 0.5) == 2.5
    assert percentile([1.0, 2.0, 3.0, 4.0, 5.0], 0.9) == pytest.approx(4.6)
    assert percentile([7.0], 0.9) == 7.0
    assert percentile([], 0.5) is None


def test_token_overlap_measures() -> None:
    assert token_f1([1, 2, 3], [1, 2, 3]) == 1.0
    assert token_f1([1, 2], [3, 4]) == 0.0
    assert token_f1([1, 1, 2], [1, 2, 2]) == pytest.approx(2 / 3)
    assert token_f1([], []) == 1.0
    assert prefix_ratio([1, 2, 9, 4], [1, 2, 3, 4]) == 0.5
    assert prefix_ratio([], []) == 1.0
    assert prefix_ratio([1], []) == 0.0


def test_call_signature_compares_name_and_arguments_only() -> None:
    assert call_signature(parse_output(CALL)) == call_signature(parse_output(CALL))
    assert call_signature(parse_output(CALL)) != call_signature(parse_output(OTHER))
    assert call_signature(parse_output("hello")) == ()


def test_mode_metrics_count_each_agreement_family_separately() -> None:
    teacher = [
        outcome(CALL),
        outcome(CALL),
        outcome("Sorry.", category="offtopic"),
        outcome("Joke!", category="injection", ok=False),
        outcome("In transit.", kind="second", category="found", ids=(1, 2, 3, 4)),
        outcome("Delayed.", kind="second", category="found", ids=(5, 6)),
    ]
    student = [
        outcome(CALL),
        outcome(OTHER),
        outcome("Sorry.", category="offtopic"),
        outcome("No.", category="injection", ok=True),
        outcome("In transit.", kind="second", category="found", ids=(1, 2, 9, 4)),
        outcome("Delayed.", kind="second", category="found", ids=(5, 6)),
    ]
    metrics = mode_metrics(student, teacher)
    text = json.dumps(metrics, allow_nan=False)
    assert json.loads(text)["samples"] == 6
    assert at(metrics, "tool_call", "decision_agreement") == {"hits": 4, "total": 4, "rate": 1.0}
    assert at(metrics, "tool_call", "exact_name_and_arguments") == {
        "hits": 1,
        "total": 2,
        "rate": 0.5,
    }
    assert at(metrics, "final_answer", "exact_text") == {"hits": 2, "total": 2, "rate": 1.0}
    assert at(metrics, "final_answer", "prefix_ratio_mean") == pytest.approx((0.5 + 1.0) / 2)
    assert at(metrics, "refusal", "agreement") == {"hits": 1, "total": 2, "rate": 0.5}
    assert at(metrics, "refusal", "teacher_refused") == {"hits": 1, "total": 2, "rate": 0.5}
    assert at(metrics, "refusal", "mode_refused") == {"hits": 2, "total": 2, "rate": 1.0}
    assert at(metrics, "prompt_tokens_mean", "rules") == 240
    assert at(metrics, "latency_ms", "first_token_ms_p50") == 100.0


def test_empty_subsets_report_a_null_rate_instead_of_dividing_by_zero() -> None:
    metrics = mode_metrics([outcome(CALL)], [outcome(CALL)])
    assert at(metrics, "final_answer", "exact_text") == {"hits": 0, "total": 0, "rate": None}
    assert at(metrics, "final_answer", "token_f1_mean") is None
    assert json.dumps(metrics, allow_nan=False)
