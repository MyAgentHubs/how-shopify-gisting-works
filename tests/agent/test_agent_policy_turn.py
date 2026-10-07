import json
from pathlib import Path

import pytest
from agent_support import (
    QUESTION,
    RENDERED,
    good_call,
    internal_of,
    public_of,
    tool_call,
)
from search_support import SEARCH
from synthetic_kb import (
    ASKED,
    NO_MATCH_REPLY,
    OFF_TOPIC,
    OFF_TOPIC_CALL,
    PARTS,
    REPAIR,
    SEARCH_CALL,
    WARRANTY,
    policy_rig,
    synthetic_tool,
)

from gisting.agent.consent import offered
from gisting.agent.policy import FallbackReason
from gisting.agent.policy_replies import MissingPhrase
from gisting.prompt.messages import AssistantMessage, Message, UserMessage
from gisting.prompt.phrases import load_phrases
from gisting.shopify.jsonvalue import JsonObject
from gisting.tools.lookup_order import ToolResponse
from gisting.tools.trace import InternalTrace, PublicOutcome, PublicTrace, Trace

MODEL_TEXT = "Happy to help with anything else."
HANDOFF_DONE = "Done. I have passed your request to our team."


class Canned:
    def __init__(self, result: JsonObject) -> None:
        self.result = result

    def call(self, arguments: JsonObject, session_id: str) -> ToolResponse:
        internal = InternalTrace(SEARCH, session_id, None, "Canned", None, "", 0)
        return ToolResponse(
            self.result, Trace(internal, PublicTrace(SEARCH, None, PublicOutcome.COMPLETED))
        )


def test_a_found_result_is_answered_by_code_with_the_top_hit_verbatim(tmp_path: Path) -> None:
    subject, spy = policy_rig(synthetic_tool(tmp_path), SEARCH_CALL, MODEL_TEXT)
    result = subject.run([UserMessage(ASKED)])
    assert result.answer == WARRANTY
    assert result.fallback_reason is None
    assert len(subject.model.prompts) == 1
    assert len(spy.calls) == 1
    internal = internal_of(result)
    assert internal["reply_source"] == "code"
    assert internal["fact_check"]["count"] == 0


def test_only_the_top_hit_is_spoken_while_the_public_list_names_up_to_three(
    tmp_path: Path,
) -> None:
    subject, _ = policy_rig(synthetic_tool(tmp_path), SEARCH_CALL, MODEL_TEXT)
    result = subject.run([UserMessage(ASKED)])
    assert REPAIR not in result.answer
    assert PARTS not in result.answer
    listed = json.loads(internal_of(result)["tool_calls"][0]["result"])["hits"]
    assert len(listed) == 3
    assert [item["id"] for item in public_of(result)["knowledge"]] == [h["id"] for h in listed]
    assert listed[0]["id"] == "kb-zz-warranty"


def test_the_public_trace_names_the_ids_and_nothing_of_the_search(tmp_path: Path) -> None:
    subject, _ = policy_rig(synthetic_tool(tmp_path), SEARCH_CALL, MODEL_TEXT)
    public = public_of(subject.run([UserMessage(ASKED)]))
    assert set(public) == {"tools", "knowledge", "tokens", "latency"}
    assert public["tools"] == [{"tool": SEARCH, "order_number": None, "outcome": "completed"}]
    assert {item["method"] for item in public["knowledge"]} == {"bm25"}
    text = json.dumps(public)
    for secret in ("zorblax", WARRANTY, REPAIR, "Zorblax warranty length", "score", "matched"):
        assert secret not in text


def test_a_no_match_is_the_approved_phrase_with_the_handoff_offer(tmp_path: Path) -> None:
    subject, _ = policy_rig(synthetic_tool(tmp_path), OFF_TOPIC_CALL, MODEL_TEXT)
    result = subject.run([UserMessage(OFF_TOPIC)])
    assert result.answer == NO_MATCH_REPLY
    assert result.fallback_reason is None
    assert len(subject.model.prompts) == 1
    assert internal_of(result)["reply_source"] == "code"
    assert public_of(result)["knowledge"] == []
    assert public_of(result)["tools"][0]["outcome"] == "completed"


def test_the_existing_consent_check_reads_the_no_match_reply_as_a_handoff_offer(
    tmp_path: Path,
) -> None:
    subject, _ = policy_rig(synthetic_tool(tmp_path), OFF_TOPIC_CALL)
    result = subject.run([UserMessage(OFF_TOPIC)])
    guard = subject.deps.policy.consent_guards["handoff_to_human"]
    assert offered(guard, result.answer)
    assert result.answer.endswith(guard.offer_text)


@pytest.mark.parametrize("agreement", ["yes", "Yes please", "ok"])
def test_a_yes_after_the_no_match_reply_opens_the_handoff(tmp_path: Path, agreement: str) -> None:
    subject, _ = policy_rig(synthetic_tool(tmp_path))
    history: list[Message] = [
        UserMessage(OFF_TOPIC),
        AssistantMessage(NO_MATCH_REPLY),
        UserMessage(agreement),
    ]
    result = subject.run(history)
    assert result.answer.startswith(HANDOFF_DONE)
    assert len(subject.handoff.calls) == 1
    assert subject.model.prompts == []


def test_a_no_after_the_no_match_reply_declines_the_handoff(tmp_path: Path) -> None:
    subject, _ = policy_rig(synthetic_tool(tmp_path))
    history: list[Message] = [
        UserMessage(OFF_TOPIC),
        AssistantMessage(NO_MATCH_REPLY),
        UserMessage("no thanks"),
    ]
    result = subject.run(history)
    assert result.answer == load_phrases().sentences["decline_ack"]
    assert subject.handoff.calls == []


def test_unreadable_knowledge_data_gives_the_upstream_error_reply_and_a_named_fallback(
    tmp_path: Path,
) -> None:
    tool = synthetic_tool(tmp_path)
    (tmp_path / "entries.jsonl").write_text("not json\n")
    subject, _ = policy_rig(tool, SEARCH_CALL, MODEL_TEXT)
    result = subject.run([UserMessage(ASKED)])
    assert result.answer == load_phrases().failure_replies["unavailable"]
    assert result.fallback_reason is FallbackReason.POLICY_UNAVAILABLE
    assert len(subject.model.prompts) == 1
    internal = internal_of(result)
    assert internal["reply_source"] == "fallback"
    assert internal["fallback_reason"] == "policy_unavailable"
    assert [e["reason"] for e in internal["fact_check"]["events"]] == ["policy_unavailable"]
    assert internal["tool_calls"][0]["trace"]["result_type"] == "PolicyUnavailable"
    public = public_of(result)
    assert public["tools"] == [{"tool": SEARCH, "order_number": None, "outcome": "unavailable"}]
    assert public["knowledge"] == []


@pytest.mark.parametrize(
    "result",
    [
        {"status": "policy_found"},
        {"status": "policy_found", "hits": []},
        {"status": "policy_found", "hits": ["kb-zz-warranty"]},
        {"status": "policy_found", "hits": [{"id": "kb-zz-warranty"}]},
        {"status": "policy_found", "hits": [{"id": "kb-zz-warranty", "answer": "  "}]},
        {"status": "policy_found", "hits": [{"id": "kb-zz-warranty", "answer": 7}]},
        {"status": "policy_unavailable"},
        {"status": "something_else"},
    ],
)
def test_a_result_code_cannot_render_goes_the_same_typed_way(result: JsonObject) -> None:
    subject, _ = policy_rig(Canned(result), SEARCH_CALL, MODEL_TEXT)
    outcome = subject.run([UserMessage(ASKED)])
    assert outcome.fallback_reason is FallbackReason.POLICY_UNAVAILABLE
    assert outcome.answer == load_phrases().failure_replies["unavailable"]
    assert len(subject.model.prompts) == 1
    assert internal_of(outcome)["fact_check"]["events"][0]["reason"] == "policy_unavailable"


def test_a_missing_no_match_phrase_fails_loudly_instead_of_replying_empty(tmp_path: Path) -> None:
    subject, _ = policy_rig(synthetic_tool(tmp_path), OFF_TOPIC_CALL, MODEL_TEXT, phrase=None)
    with pytest.raises(MissingPhrase, match="policy_no_match"):
        subject.run([UserMessage(OFF_TOPIC)])


def test_a_found_answer_and_the_upstream_error_do_not_need_the_no_match_phrase(
    tmp_path: Path,
) -> None:
    subject, _ = policy_rig(synthetic_tool(tmp_path), SEARCH_CALL, phrase=None)
    assert subject.run([UserMessage(ASKED)]).answer == WARRANTY


def test_a_refused_query_is_not_run_and_a_corrected_one_is_answered_by_code(
    tmp_path: Path,
) -> None:
    refused = tool_call(SEARCH, query="zorblax guarantee")
    subject, spy = policy_rig(synthetic_tool(tmp_path), refused, SEARCH_CALL, MODEL_TEXT)
    result = subject.run([UserMessage(ASKED)])
    assert [call[0] for call in spy.calls] == [{"query": "zorblax warranty"}]
    assert result.answer == WARRANTY
    assert len(subject.model.prompts) == 2
    problems = [call["problem"] for call in internal_of(result)["tool_calls"]]
    assert problems == ["query_term_not_in_latest_message", None]
    assert "query_term_not_in_latest_message" not in json.dumps(public_of(result))


def test_a_refused_query_leaves_no_trace_in_the_public_projection(tmp_path: Path) -> None:
    refused = tool_call(SEARCH, query="zorblax guarantee")
    subject, spy = policy_rig(synthetic_tool(tmp_path), refused, MODEL_TEXT)
    result = subject.run([UserMessage(ASKED)])
    assert spy.calls == []
    assert result.answer == MODEL_TEXT
    public = public_of(result)
    assert public["tools"] == []
    assert public["knowledge"] == []


def test_a_lookup_in_the_turn_ends_it_so_a_later_search_never_runs(tmp_path: Path) -> None:
    subject, spy = policy_rig(synthetic_tool(tmp_path), good_call(), SEARCH_CALL, MODEL_TEXT)
    result = subject.run([UserMessage(QUESTION)])
    assert result.answer == RENDERED
    assert spy.calls == []
    assert len(subject.model.prompts) == 1
    assert public_of(result)["knowledge"] == []


def test_a_search_beside_a_lookup_is_rejected_and_never_run(tmp_path: Path) -> None:
    both = good_call() + "\n" + tool_call(SEARCH, query="order")
    subject, spy = policy_rig(synthetic_tool(tmp_path), both, MODEL_TEXT)
    subject.run([UserMessage(QUESTION)])
    assert spy.calls == []
    assert subject.tool.calls == []
