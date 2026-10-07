import json
import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from gisting.eval.case import Verdict
from gisting.prompt.parse import ParsedOutput
from gisting.shopify.jsonvalue import JsonObject

REFUSAL_CATEGORIES = ("offtopic", "injection")


@dataclass(frozen=True)
class Outcome:
    sample_id: str
    kind: str
    category: str
    text: str
    ids: tuple[int, ...]
    parsed: ParsedOutput
    verdict: Verdict
    prompt_tokens: dict[str, int]
    first_token_ms: float
    total_ms: float


def percentile(values: Sequence[float], fraction: float) -> float | None:
    ordered = sorted(values)
    if not ordered:
        return None
    position = (len(ordered) - 1) * fraction
    low, high = math.floor(position), math.ceil(position)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def token_f1(left: Sequence[int], right: Sequence[int]) -> float:
    if not left and not right:
        return 1.0
    shared = sum((Counter(left) & Counter(right)).values())
    if shared == 0:
        return 0.0
    precision, recall = shared / len(left), shared / len(right)
    return 2 * precision * recall / (precision + recall)


def prefix_ratio(student: Sequence[int], teacher: Sequence[int]) -> float:
    if not teacher:
        return 1.0 if not student else 0.0
    agree = 0
    for left, right in zip(student, teacher, strict=False):
        if left != right:
            break
        agree += 1
    return agree / len(teacher)


def call_signature(parsed: ParsedOutput) -> tuple[str, ...]:
    return tuple(
        json.dumps([call.name, call.arguments, call.problem], sort_keys=True, default=str)
        for call in parsed.calls
    )


def rate(hits: int, total: int) -> JsonObject:
    return {"hits": hits, "total": total, "rate": hits / total if total else None}


def mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def tool_call_rows(pairs: Sequence[tuple[Outcome, Outcome]]) -> JsonObject:
    first = [(m, t) for m, t in pairs if t.kind == "first"]
    called = [(m, t) for m, t in first if t.parsed.calls]
    return {
        "decision_agreement": rate(
            sum(bool(m.parsed.calls) == bool(t.parsed.calls) for m, t in first), len(first)
        ),
        "exact_name_and_arguments": rate(
            sum(call_signature(m.parsed) == call_signature(t.parsed) for m, t in called),
            len(called),
        ),
    }


def final_answer_rows(pairs: Sequence[tuple[Outcome, Outcome]]) -> JsonObject:
    second = [(m, t) for m, t in pairs if t.kind == "second"]
    return {
        "exact_text": rate(sum(m.text == t.text for m, t in second), len(second)),
        "token_f1_mean": mean([token_f1(m.ids, t.ids) for m, t in second]),
        "prefix_ratio_mean": mean([prefix_ratio(m.ids, t.ids) for m, t in second]),
    }


def refusal_rows(pairs: Sequence[tuple[Outcome, Outcome]]) -> JsonObject:
    chosen = [(m, t) for m, t in pairs if t.kind == "first" and t.category in REFUSAL_CATEGORIES]
    return {
        "agreement": rate(sum(m.verdict.ok == t.verdict.ok for m, t in chosen), len(chosen)),
        "mode_refused": rate(sum(m.verdict.ok for m, _ in chosen), len(chosen)),
        "teacher_refused": rate(sum(t.verdict.ok for _, t in chosen), len(chosen)),
    }


def token_rows(outcomes: Sequence[Outcome]) -> JsonObject:
    keys = ("rules", "tools", "history", "tool_results", "total")
    return {key: mean([o.prompt_tokens[key] for o in outcomes]) for key in keys}


def latency_rows(outcomes: Sequence[Outcome]) -> JsonObject:
    first = [o.first_token_ms for o in outcomes]
    total = [o.total_ms for o in outcomes]
    return {
        "first_token_ms_p50": percentile(first, 0.5),
        "first_token_ms_p90": percentile(first, 0.9),
        "total_ms_p50": percentile(total, 0.5),
        "total_ms_p90": percentile(total, 0.9),
    }


def mode_metrics(outcomes: Sequence[Outcome], teacher: Sequence[Outcome]) -> JsonObject:
    pairs = list(zip(outcomes, teacher, strict=True))
    return {
        "samples": len(pairs),
        "exact_text_all": rate(sum(m.text == t.text for m, t in pairs), len(pairs)),
        "tool_call": tool_call_rows(pairs),
        "final_answer": final_answer_rows(pairs),
        "refusal": refusal_rows(pairs),
        "heuristic_judge_ok": rate(sum(o.verdict.ok for o in outcomes), len(outcomes)),
        "prompt_tokens_mean": token_rows(outcomes),
        "latency_ms": latency_rows(outcomes),
    }
