import json
import math
from pathlib import Path

import pytest
from policy_support import build, hit_ids, hits_of, raw_score

from gisting.shopify.jsonvalue import JsonObject
from gisting.tools.lookup_order import ToolResponse
from gisting.tools.search_policy import InvalidPolicyCall, SearchPolicy
from gisting.tools.trace import PublicOutcome, internal_json, public_json

SESSION = "session-1"
FRUIT = {"kb-a": "apple pear plum", "kb-b": "apple fig", "kb-c": "kiwi lime"}


def call(tool: SearchPolicy, query: str) -> ToolResponse:
    return tool.call({"query": query}, SESSION)


def test_a_covered_question_returns_the_hits_with_only_the_four_public_fields() -> None:
    response = call(SearchPolicy(), "can I pay with paypal")
    assert response.result["status"] == "policy_found"
    hits = hits_of(response)
    assert 1 <= len(hits) <= 3
    first = hits[0]
    assert set(first) == {"id", "category", "title", "answer"}
    assert first["id"] == "kb-pay-methods"
    assert response.trace.public.outcome is PublicOutcome.COMPLETED
    assert public_json(response.trace.public)["order_number"] is None


def test_a_question_outside_the_knowledge_base_is_a_bare_no_match() -> None:
    response = call(SearchPolicy(), "what is the capital of France")
    assert response.result == {"status": "policy_no_match"}
    assert response.trace.public.outcome is PublicOutcome.COMPLETED


def test_the_result_serialises_with_sorted_keys_and_no_scores() -> None:
    text = json.dumps(call(SearchPolicy(), "can I pay with paypal").result, sort_keys=True)
    assert "score" not in text and "matched" not in text


def test_hits_never_exceed_the_data_limit(tmp_path: Path) -> None:
    answers = {f"kb-{n}": f"apple word{n}" for n in range(6)}
    response = call(build(tmp_path, answers), "apple")
    assert response.result["status"] == "policy_found"
    assert len(hit_ids(response)) == 3


def test_a_hit_exactly_at_min_score_is_kept_and_one_ulp_above_is_rejected(tmp_path: Path) -> None:
    score = raw_score(FRUIT, "apple pear")
    kept = call(build(tmp_path, FRUIT, min_score=score), "apple pear")
    assert kept.result["status"] == "policy_found"
    rejected = call(build(tmp_path, FRUIT, min_score=math.nextafter(score, math.inf)), "apple pear")
    assert rejected.result == {"status": "policy_no_match"}


def test_a_hit_with_exactly_min_matched_terms_is_kept_and_one_fewer_is_rejected(
    tmp_path: Path,
) -> None:
    kept = call(build(tmp_path, FRUIT, min_matched_terms=2), "apple pear")
    assert hit_ids(kept) == ["kb-a"]
    rejected = call(build(tmp_path, FRUIT, min_matched_terms=3), "apple pear")
    assert rejected.result == {"status": "policy_no_match"}


def test_each_hit_is_judged_separately_so_weak_lower_hits_are_dropped(tmp_path: Path) -> None:
    response = call(build(tmp_path, FRUIT, min_matched_terms=2), "apple pear")
    assert hit_ids(response) == ["kb-a"]


def test_internal_trace_lists_every_candidate_with_score_even_when_rejected(tmp_path: Path) -> None:
    response = call(build(tmp_path, FRUIT, min_matched_terms=3), "apple pear")
    internal = internal_json(response.trace.internal)
    assert internal["tool"] == "search_policy"
    assert internal["session_id"] == SESSION
    assert internal["result_type"] == "PolicyNoMatch"
    candidates = json.loads(str(internal["detail"]))
    assert [item["id"] for item in candidates] == ["kb-a", "kb-b"]
    assert candidates[0]["matched_terms"] == 2
    assert candidates[0]["score"] > candidates[1]["score"] > 0


def test_internal_result_type_is_policy_found_for_a_hit() -> None:
    response = call(SearchPolicy(), "can I pay with paypal")
    assert response.trace.internal.result_type == "PolicyFound"


@pytest.mark.parametrize("broken", ["entries", "params", "both"])
def test_unreadable_knowledge_base_data_is_an_unavailable_result_not_an_exception(
    tmp_path: Path, broken: str
) -> None:
    tool = build(tmp_path, FRUIT)
    if broken in {"entries", "both"}:
        (tmp_path / "entries.jsonl").write_text("not json\n")
    if broken in {"params", "both"}:
        (tmp_path / "params.json").unlink()
    response = call(tool, "apple")
    assert response.result == {"status": "policy_unavailable"}
    assert response.trace.public.outcome is PublicOutcome.UNAVAILABLE
    assert response.trace.internal.result_type == "PolicyUnavailable"
    assert "KbDataError" in str(response.trace.internal.detail)


def test_params_with_out_of_range_values_are_unavailable(tmp_path: Path) -> None:
    response = call(build(tmp_path, FRUIT, min_score=-1), "apple")
    assert response.result == {"status": "policy_unavailable"}


@pytest.mark.parametrize(
    "arguments",
    [{}, {"query": 5}, {"query": None}, {"query": "x", "top_k": 3}, {"q": "x"}],
    ids=["missing", "number", "null", "extra_key", "wrong_key"],
)
def test_arguments_must_be_exactly_one_query_string(arguments: JsonObject) -> None:
    with pytest.raises(InvalidPolicyCall):
        SearchPolicy().call(arguments, SESSION)


def test_a_blank_query_is_a_no_match() -> None:
    assert call(SearchPolicy(), "   ").result == {"status": "policy_no_match"}
