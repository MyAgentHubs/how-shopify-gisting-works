import json
from typing import Any

import pytest
from agent_support import CANARY, internal_of, public_of, rig

from gisting.agent.public_trace import PublicTrace
from gisting.agent.trace import GenerationRecord, Recorder, RunContext, ToolRecord, build_traces
from gisting.eval.dataclass_json import DecodeError, decode_as
from gisting.prompt.segments import PromptStats
from gisting.tools.outcomes import PolicyFound, PolicyHit
from gisting.tools.search_policy import TOOL_NAME, render_policy

ID_ONE = "kb-ship-standard"
ID_TWO = "kb-return-window"
ID_THREE = "kb-ship-express"
ID_FOUR = "kb-ship-processing"
KNOWN = frozenset({ID_ONE, ID_TWO, ID_THREE, ID_FOUR})
BODY = "Standard shipping within the United States takes 3 to 7 business days."
QUERY = "my order GLR-ABCD1234 never came"


def hit(identifier: str, **extra: object) -> dict[str, object]:
    return {
        "id": identifier,
        "category": "shipping",
        "title": "Standard shipping time",
        "answer": BODY,
        **extra,
    }


def search_record(result: object, name: str = TOOL_NAME) -> ToolRecord:
    public = {"tool": name, "order_number": None, "outcome": "completed"}
    return ToolRecord(name, {"query": QUERY}, None, public, {"tool": name}, json.dumps(result))


def found(*hits: dict[str, object]) -> ToolRecord:
    return search_record({"status": "policy_found", "hits": list(hits)})


def traces(*records: ToolRecord) -> tuple[dict[str, Any], dict[str, Any]]:
    recorder = Recorder()
    recorder.generations.append(
        GenerationRecord(PromptStats(100, 50, 10, 0, 160), "x", 1, 1.0, 2.0, "stop")
    )
    recorder.tools.extend(records)
    built = build_traces(recorder, RunContext("fake", known_ids=KNOWN), 3.0, None)
    return json.loads(json.dumps(built.public)), json.loads(json.dumps(built.internal))


def knowledge(*records: ToolRecord) -> list[dict[str, str]]:
    return traces(*records)[0]["knowledge"]


def test_the_status_the_projection_reads_is_the_one_the_tool_writes() -> None:
    written = render_policy(PolicyFound((PolicyHit(ID_ONE, "shipping", "t", "a"),)))
    assert knowledge(search_record(dict(written))) == [{"id": ID_ONE, "method": "bm25"}]


def test_a_turn_without_a_policy_search_has_an_empty_knowledge_list() -> None:
    assert traces()[0]["knowledge"] == []
    assert public_of(rig("Hello there").run())["knowledge"] == []


def test_found_hits_become_ids_with_the_method_in_their_original_order() -> None:
    assert knowledge(found(hit(ID_ONE), hit(ID_TWO), hit(ID_THREE))) == [
        {"id": ID_ONE, "method": "bm25"},
        {"id": ID_TWO, "method": "bm25"},
        {"id": ID_THREE, "method": "bm25"},
    ]


@pytest.mark.parametrize("status", ["policy_no_match", "policy_unavailable"])
def test_no_match_and_unavailable_read_as_no_hit(status: str) -> None:
    assert knowledge(search_record({"status": status})) == []


@pytest.mark.parametrize(
    "result",
    [
        {"status": "policy_found"},
        {"status": "policy_found", "hits": "kb-x"},
        {"status": "policy_found", "hits": [None, 3, "kb-x", ["kb-x"]]},
        {"status": "policy_found", "hits": [{"title": "no id"}]},
        {"status": "policy_found", "hits": [{"id": 7}]},
        {"hits": [hit(ID_ONE)]},
        {"status": "found", "hits": [hit(ID_ONE)]},
        ["policy_found"],
    ],
)
def test_a_malformed_search_result_yields_no_knowledge_and_no_error(result: object) -> None:
    assert knowledge(search_record(result)) == []


def test_a_result_that_is_not_json_yields_no_knowledge() -> None:
    record = ToolRecord(TOOL_NAME, {}, None, None, None, "not json {")
    assert knowledge(record) == []


def test_more_than_three_hits_are_cut_to_the_first_three() -> None:
    assert [
        item["id"]
        for item in knowledge(found(*(hit(i) for i in (ID_ONE, ID_TWO, ID_THREE, ID_FOUR))))
    ] == [ID_ONE, ID_TWO, ID_THREE]


def test_two_searches_in_one_turn_merge_without_repeats_up_to_three() -> None:
    first, second = found(hit(ID_ONE), hit(ID_TWO)), found(hit(ID_TWO), hit(ID_THREE), hit(ID_FOUR))
    assert [item["id"] for item in knowledge(first, second)] == [ID_ONE, ID_TWO, ID_THREE]


def test_only_search_policy_records_count() -> None:
    result = {"status": "policy_found", "hits": [hit(ID_ONE)]}
    assert knowledge(search_record(result, name="lookup_order")) == []
    assert knowledge(search_record(result, name="handoff_to_human")) == []


def test_a_search_call_that_was_rejected_before_running_adds_nothing() -> None:
    assert knowledge(ToolRecord(TOOL_NAME, {"query": 3}, "arguments must be a string")) == []


@pytest.mark.parametrize(
    "extra",
    [
        {"canary": CANARY, "score": 9.5, "matched_terms": 4},
        {"order": {"order_number": "#1003", "canary": CANARY}, "email": "x@example.com"},
        {"method": "dense", "query": QUERY, "candidates": [ID_FOUR]},
    ],
)
def test_the_public_knowledge_carries_only_the_id_and_the_method(extra: dict[str, object]) -> None:
    public, _ = traces(found(hit(ID_ONE, **extra)))
    assert public["knowledge"] == [{"id": ID_ONE, "method": "bm25"}]
    text = json.dumps(public)
    for secret in (CANARY, BODY, QUERY, "Standard shipping time", "9.5", "x@example.com"):
        assert secret not in text


@pytest.mark.parametrize(
    "bad",
    ["", "KB-ship", "kb-", "kb-Ship", "kb_ship", "kb-ship\n", f"kb-{CANARY}", "kb-a b", "x-kb-a"],
)
def test_an_id_that_does_not_look_like_a_kb_id_is_dropped_and_visible_internally(bad: str) -> None:
    public, internal = traces(found(hit(bad), hit(ID_ONE)))
    assert public["knowledge"] == [{"id": ID_ONE, "method": "bm25"}]
    assert CANARY not in json.dumps(public)
    assert bad in internal["knowledge_dropped"]


def test_a_dropped_entry_does_not_take_a_place_among_the_three() -> None:
    public, internal = traces(found(hit("bad id"), hit(ID_ONE), hit(ID_TWO), hit(ID_THREE)))
    assert [item["id"] for item in public["knowledge"]] == [ID_ONE, ID_TWO, ID_THREE]
    assert internal["knowledge_dropped"] == ["bad id"]


def test_the_internal_trace_lists_nothing_dropped_when_every_id_is_valid() -> None:
    assert traces(found(hit(ID_ONE)))[1]["knowledge_dropped"] == []
    assert internal_of(rig("Hello there").run())["knowledge_dropped"] == []


def test_the_tool_list_shows_the_search_without_an_order_number_for_any_result() -> None:
    results = [
        {"status": "policy_found", "hits": [hit(ID_ONE, canary=CANARY)]},
        {"status": "policy_no_match"},
    ]
    for result in results:
        public, _ = traces(search_record(result))
        assert public["tools"] == [
            {"tool": TOOL_NAME, "order_number": None, "outcome": "completed"}
        ]
        assert CANARY not in json.dumps(public["tools"])


def test_a_public_trace_with_knowledge_decodes_into_the_contract() -> None:
    public, _ = traces(found(hit(ID_ONE), hit(ID_TWO)))
    trace = decode_as(PublicTrace, public)
    assert [(item.id, item.method) for item in trace.knowledge] == [
        (ID_ONE, "bm25"),
        (ID_TWO, "bm25"),
    ]


def test_a_public_trace_without_the_knowledge_field_breaks_the_contract() -> None:
    public, _ = traces()
    del public["knowledge"]
    with pytest.raises(DecodeError):
        decode_as(PublicTrace, public)


def test_an_unknown_retrieval_method_breaks_the_contract() -> None:
    public, _ = traces()
    public["knowledge"] = [{"id": ID_ONE, "method": "dense"}]
    with pytest.raises(DecodeError):
        decode_as(PublicTrace, public)
