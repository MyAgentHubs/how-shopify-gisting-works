import json
from pathlib import Path
from typing import Any

import pytest
from agent_support import CANARY, internal_of, public_of
from synthetic_kb import ASKED, SEARCH_CALL, policy_rig, synthetic_tool

from gisting.agent.knowledge import project_knowledge
from gisting.agent.public_trace import MAX_KNOWLEDGE
from gisting.agent.trace import GenerationRecord, Recorder, RunContext, ToolRecord, build_traces
from gisting.kb.entries import ENTRY_ID, MAX_ID_LENGTH
from gisting.prompt.messages import UserMessage
from gisting.prompt.segments import PromptStats
from gisting.tools.search_policy import TOOL_NAME

LONGEST = "kb-" + "a" * (MAX_ID_LENGTH - 3)
KNOWN = frozenset({"kb-one", "kb-two", "kb-three", "kb-four", "kb-five", LONGEST})


def found(*ids: object) -> str:
    hits = [{"id": identifier, "answer": "x"} for identifier in ids]
    return json.dumps({"status": "policy_found", "hits": hits})


def projected(*texts: str | None, known: frozenset[str] = KNOWN) -> tuple[list[str], Any]:
    knowledge = project_knowledge([(TOOL_NAME, text) for text in texts], known)
    return [item["id"] for item in knowledge.public], knowledge


def test_the_limit_and_the_id_length_are_what_the_contract_says() -> None:
    assert (MAX_KNOWLEDGE, MAX_ID_LENGTH) == (3, 64)
    assert ENTRY_ID.fullmatch(LONGEST)


def test_an_id_with_a_valid_shape_that_is_not_in_the_loaded_kb_is_dropped_and_named() -> None:
    shown, knowledge = projected(found("kb-one", "kb-unknown", "kb-two"))
    assert shown == ["kb-one", "kb-two"]
    assert knowledge.dropped == ("kb-unknown",)


def test_an_empty_allowlist_drops_every_id_and_names_them() -> None:
    shown, knowledge = projected(found("kb-one", "kb-two"), known=frozenset())
    assert shown == []
    assert knowledge.dropped == ("kb-one", "kb-two")


@pytest.mark.parametrize(
    "identifier", ["kb-one\n", "KB-one", "kb-", "kb--one", "kb-one ", "kb_one", LONGEST + "a"]
)
def test_the_shape_and_the_length_are_checked_even_for_an_id_the_caller_listed(
    identifier: str,
) -> None:
    shown, knowledge = projected(found(identifier), known=KNOWN | {identifier})
    assert shown == []
    assert knowledge.dropped == (identifier,)


def test_the_longest_allowed_id_passes() -> None:
    assert projected(found(LONGEST))[0] == [LONGEST]


def test_ids_past_the_limit_are_not_public_and_are_named_in_the_order_met() -> None:
    shown, knowledge = projected(found("kb-one", "kb-two", "kb-three", "kb-four", "kb-five"))
    assert shown == ["kb-one", "kb-two", "kb-three"]
    assert knowledge.truncated == ("kb-four", "kb-five")


def test_a_repeated_id_is_neither_truncated_nor_shown_twice() -> None:
    shown, knowledge = projected(found("kb-one", "kb-two"), found("kb-two", "kb-one", "kb-three"))
    assert shown == ["kb-one", "kb-two", "kb-three"]
    assert knowledge.truncated == ()
    assert knowledge.malformed == 0


@pytest.mark.parametrize(
    ("text", "count"),
    [
        ("not json {", 1),
        ("[]", 1),
        ("null", 1),
        (json.dumps({"hits": [{"id": "kb-one"}]}), 1),
        (json.dumps({"status": "policy_found"}), 1),
        (json.dumps({"status": "policy_found", "hits": "kb-one"}), 1),
        (json.dumps({"status": "policy_found", "hits": []}), 1),
        (json.dumps({"status": "found", "hits": [{"id": "kb-one"}]}), 1),
        (json.dumps({"status": "policy_found", "hits": [None, 3, "kb-one", ["kb-one"]]}), 4),
        (json.dumps({"status": "policy_found", "hits": [{"title": "no id"}, {"id": 7}]}), 2),
        (json.dumps({"status": "policy_found", "hits": [{"id": None}, {"id": ["kb-one"]}]}), 2),
    ],
)
def test_a_result_that_cannot_be_read_is_counted_by_its_unreadable_parts(
    text: str, count: int
) -> None:
    shown, knowledge = projected(text)
    assert shown == []
    assert knowledge.malformed == count
    assert knowledge.dropped == ()


@pytest.mark.parametrize("status", ["policy_no_match", "policy_unavailable"])
def test_a_quiet_result_is_not_a_malformed_one(status: str) -> None:
    shown, knowledge = projected(json.dumps({"status": status}))
    assert (shown, knowledge.malformed, knowledge.dropped, knowledge.truncated) == ([], 0, (), ())


def test_a_search_that_never_ran_has_no_result_and_counts_for_nothing() -> None:
    assert projected(None)[1].malformed == 0


def test_other_tools_are_not_read() -> None:
    knowledge = project_knowledge([("lookup_order", found("kb-one"))], KNOWN)
    assert knowledge.public == ()
    assert knowledge.malformed == 0


def build(*records: ToolRecord) -> dict[str, Any]:
    recorder = Recorder()
    recorder.generations.append(
        GenerationRecord(PromptStats(100, 50, 10, 0, 160), "x", 1, 1.0, 2.0, "stop")
    )
    recorder.tools.extend(records)
    built = build_traces(recorder, RunContext("fake", known_ids=KNOWN), 3.0, None)
    return json.loads(json.dumps({"public": built.public, "internal": built.internal}))


def record(text: str, internal: dict[str, object] | None = None) -> ToolRecord:
    public = {"tool": TOOL_NAME, "order_number": None, "outcome": "completed"}
    return ToolRecord(
        TOOL_NAME, {"query": "q"}, None, public, internal or {"tool": TOOL_NAME}, text
    )


def test_the_internal_trace_names_what_was_dropped_cut_or_unreadable() -> None:
    both = build(
        record(found("kb-one", "kb-nope", "kb-two", "kb-three", "kb-four")),
        record("not json"),
    )
    internal = both["internal"]
    assert internal["knowledge_dropped"] == ["kb-nope"]
    assert internal["knowledge_truncated"] == ["kb-four"]
    assert internal["knowledge_malformed"] == 1
    assert [item["id"] for item in both["public"]["knowledge"]] == ["kb-one", "kb-two", "kb-three"]


def test_none_of_the_internal_counts_reach_the_public_projection() -> None:
    both = build(record(found("kb-one", CANARY, "kb-two", "kb-three", "kb-four")), record("x"))
    text = json.dumps(both["public"])
    for name in ("dropped", "truncated", "malformed", CANARY, "kb-four"):
        assert name not in text


def test_a_reused_search_result_is_not_counted_twice() -> None:
    reused = record("not json", {"reused": True, "result_type": "PolicyFound"})
    both = build(record("not json"), reused)
    assert both["internal"]["knowledge_malformed"] == 1


def test_a_quiet_turn_has_zero_counts() -> None:
    internal = build()["internal"]
    assert internal["knowledge_dropped"] == []
    assert internal["knowledge_truncated"] == []
    assert internal["knowledge_malformed"] == 0


def test_a_turn_with_the_loaded_ids_shows_them_and_one_without_names_every_drop(
    tmp_path: Path,
) -> None:
    subject, _ = policy_rig(synthetic_tool(tmp_path), SEARCH_CALL)
    shown = [item["id"] for item in public_of(subject.run([UserMessage(ASKED)]))["knowledge"]]
    assert shown[0] == "kb-zz-warranty"
    blind, _ = policy_rig(synthetic_tool(tmp_path), SEARCH_CALL, ids=frozenset())
    quiet = blind.run([UserMessage(ASKED)])
    assert public_of(quiet)["knowledge"] == []
    assert internal_of(quiet)["knowledge_dropped"] == shown
