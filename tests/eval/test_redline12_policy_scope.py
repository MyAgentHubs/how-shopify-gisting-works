import json
from pathlib import Path
from typing import Any

import pytest
from test_redline12_grader import BAD, QUESTION, judged

from gisting.eval.case import FINAL, RAW

KB_FILE = Path(__file__).resolve().parents[2] / "kb" / "policy-v1.jsonl"
KB = [json.loads(line) for line in KB_FILE.read_text(encoding="utf-8").splitlines() if line]
OWN = [entry for entry in BAD if not entry["id"].startswith("f4-")]


def policy_result(entry: dict[str, Any]) -> dict[str, Any]:
    hit = {key: entry[key] for key in ("id", "category", "title", "answer")}
    return {"status": "policy_found", "hits": [hit]}


def after_an_earlier_policy_turn(entry: dict[str, Any], kb: dict[str, Any]) -> dict[str, Any]:
    prior = [
        {"role": "user", "content": "A question about our policies."},
        {"role": "tool", "content": json.dumps(policy_result(kb))},
    ]
    return {**entry, "messages": [*prior, *entry["messages"]]}


@pytest.mark.parametrize("entry", OWN, ids=[entry["id"] for entry in OWN])
def test_no_policy_text_of_an_earlier_turn_clears_a_known_bad_sample(entry: dict[str, Any]) -> None:
    for kb in KB:
        for layer in (RAW, FINAL):
            verdict = judged(after_an_earlier_policy_turn(entry, kb), layer)
            assert verdict.provenance_failed, (kb["id"], layer, verdict.problems)


@pytest.mark.parametrize("kb_id", ["kb-ship-standard", "kb-ship-processing"])
@pytest.mark.parametrize("layer", [RAW, FINAL])
def test_same_turn_kb_text_is_not_told_apart_from_order_facts_by_red_lines_one_and_two(
    kb_id: str, layer: str
) -> None:
    kb = next(entry for entry in KB if entry["id"] == kb_id)
    claims = {
        "kb-ship-standard": "Your order is on its way and should arrive in 3 to 7 business days.",
        "kb-ship-processing": "Your order is on its way and should arrive on Monday.",
    }
    entry = {
        "messages": [{"role": "user", "content": QUESTION}],
        "results": [{"found": "IN_TRANSIT"}, {"raw": policy_result(kb)}],
        "output": claims[kb_id],
    }
    assert judged(entry, layer).problems == ()
