import json
from dataclasses import replace
from pathlib import Path

import pytest
from agent_support import internal_of, public_of, tool_call
from search_support import SEARCH, search_rig
from synthetic_kb import worded

from gisting.agent.policy import (
    INVALID_STATUS,
    AgentPolicyError,
    FallbackReason,
    InvalidCode,
    load_agent_policy,
)
from gisting.agent.search_guard import QueryRefusal
from gisting.prompt.messages import Message, UserMessage

ASKED = "What is your refund policy?"
ANSWER = "Happy to help with anything else."
POLICY_FILE = Path(__file__).resolve().parents[2] / "prompts" / "agent_policy.json"


def search_call(query: str) -> str:
    return tool_call(SEARCH, query=query)


def test_a_grounded_query_runs_the_tool_once_and_leaves_no_problem_in_the_trace() -> None:
    subject, spy = search_rig(search_call("refund policy"), ANSWER)
    result = subject.run([UserMessage(ASKED)])
    assert len(spy.calls) == 1
    assert result.fallback_reason is None
    assert [call["problem"] for call in internal_of(result)["tool_calls"]] == [None]
    assert internal_of(result)["guard"]["count"] == 0


def test_the_tool_and_the_internal_trace_get_only_the_checked_words() -> None:
    noisy = "The REFUND, policy!! ｐｏｌｉｃｙ 🙂 \u202e"
    subject, spy = search_rig(search_call(noisy), ANSWER)
    result = subject.run([UserMessage(ASKED)])
    assert [arguments for arguments, _ in spy.calls] == [{"query": "refund policy"}]
    record = internal_of(result)["tool_calls"][0]
    assert record["arguments"] == {"query": "refund policy"}
    assert record["problem"] is None


def test_a_refused_query_never_reaches_the_tool_and_is_named_in_the_internal_trace() -> None:
    subject, spy = search_rig(search_call("refund warranty"), ANSWER)
    result = subject.run([UserMessage(ASKED)])
    assert spy.calls == []
    assert internal_of(result)["tool_calls"][0]["problem"] == QueryRefusal.TERM_NOT_SAID.value
    assert result.answer == ANSWER


def test_the_model_sees_only_the_generic_code_and_the_public_trace_stays_silent() -> None:
    subject, _ = search_rig(search_call("refund warranty"), ANSWER)
    result = subject.run([UserMessage(ASKED)])
    seen = subject.prompt_text(1)
    assert json.dumps({"status": INVALID_STATUS, "code": InvalidCode.QUERY_REFUSED}) in seen
    assert all(item.value not in seen for item in QueryRefusal)
    public = json.dumps(public_of(result))
    assert public_of(result)["tools"] == []
    assert all(item.value not in public for item in QueryRefusal)
    assert "query_refused" not in public


def test_the_model_may_retry_once_with_a_corrected_query() -> None:
    subject, spy = search_rig(search_call("refund warranty"), search_call("refund"), ANSWER)
    subject.deps = replace(subject.deps, policy=worded(subject.deps.policy))
    result = subject.run([UserMessage(ASKED)])
    assert [call[0] for call in spy.calls] == [{"query": "refund"}]
    assert result.fallback_reason is None
    assert internal_of(result)["reply_source"] == "code"
    assert len(subject.model.prompts) == 2
    problems = [call["problem"] for call in internal_of(result)["tool_calls"]]
    assert problems == [QueryRefusal.TERM_NOT_SAID.value, None]


def test_a_second_refused_query_ends_the_turn_with_the_invalid_call_fallback() -> None:
    subject, spy = search_rig(search_call("warranty"), search_call("shipping"))
    result = subject.run([UserMessage(ASKED)])
    assert spy.calls == []
    assert result.fallback_reason is FallbackReason.INVALID_TOOL_CALL


def test_a_query_on_a_message_that_is_not_the_latest_one_does_not_count() -> None:
    subject, spy = search_rig(search_call("shipping refund"), search_call("shipping refund"))
    history: list[Message] = [UserMessage("How long is shipping?"), UserMessage(ASKED)]
    result = subject.run(history)
    assert spy.calls == []
    assert result.fallback_reason is FallbackReason.INVALID_TOOL_CALL


def test_a_search_call_beside_another_call_is_still_checked() -> None:
    both = search_call("warranty") + "\n" + tool_call("handoff_to_human")
    subject, spy = search_rig(both, ANSWER)
    subject.run([UserMessage(ASKED)])
    assert spy.calls == []
    assert subject.handoff.calls == []


def test_the_registered_tool_is_read_only_and_grounded_on_its_query() -> None:
    policy = load_agent_policy()
    assert policy.grounded_arguments[SEARCH] == {"query": "query_terms"}
    assert SEARCH in policy.consent_exempt
    assert SEARCH not in policy.consent_guards


def test_the_limits_and_filler_words_come_from_data() -> None:
    policy = load_agent_policy()
    assert (policy.query_limits.max_chars, policy.query_limits.max_terms) == (160, 16)
    assert {"the", "what", "please"} <= policy.search_params.stopwords
    tight = replace(policy.query_limits, max_terms=1)
    subject, spy = search_rig(search_call("refund policy"), ANSWER)
    subject.deps = replace(subject.deps, policy=replace(policy, query_limits=tight))
    subject.run([UserMessage(ASKED)])
    assert spy.calls == []


@pytest.mark.parametrize(
    "limits",
    [{}, {"max_chars": 0, "max_terms": 5}, {"max_chars": 5, "max_terms": 0}, {"max_chars": "5"}],
)
def test_malformed_query_limits_are_rejected_when_the_policy_loads(
    tmp_path: Path, limits: dict[str, object]
) -> None:
    document = json.loads(POLICY_FILE.read_text())
    document["query_limits"] = limits
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(document))
    with pytest.raises(AgentPolicyError):
        load_agent_policy(path)


def test_a_broken_search_parameter_file_stops_the_policy_from_loading(tmp_path: Path) -> None:
    broken = tmp_path / "params.json"
    broken.write_text("{")
    with pytest.raises(AgentPolicyError):
        load_agent_policy(POLICY_FILE, broken)
    with pytest.raises(AgentPolicyError):
        load_agent_policy(POLICY_FILE, tmp_path / "missing.json")
