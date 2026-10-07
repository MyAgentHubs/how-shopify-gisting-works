import json
from pathlib import Path

import pytest
from agent_support import good_call, internal_of, tool_call
from search_support import SEARCH
from synthetic_kb import ASKED, SEARCH_CALL, WARRANTY, policy_rig, synthetic_tool

from gisting.agent.policy import FallbackReason, InvalidCode
from gisting.prompt.messages import UserMessage

COMPOUND = "How long is the zorblax warranty, and are zorblax repairs free?"
REPAIR_CALL = tool_call(SEARCH, query="zorblax repairs")
TWO_SEARCHES = SEARCH_CALL + REPAIR_CALL
MODEL_TEXT = "Our warranty lasts a lifetime and repairs are always free."
HANDOFF = tool_call("handoff_to_human")


def test_the_code_the_model_is_told_names_one_search_at_a_time() -> None:
    assert InvalidCode.ONE_SEARCH_AT_A_TIME.value == "one_search_at_a_time"


@pytest.mark.parametrize(
    "first",
    [TWO_SEARCHES, SEARCH_CALL + HANDOFF, HANDOFF + SEARCH_CALL, SEARCH_CALL + good_call()],
    ids=["two_searches", "search_then_handoff", "handoff_first", "search_then_lookup"],
)
def test_a_search_that_shares_its_block_is_rejected_unexecuted_and_the_model_may_correct_it(
    tmp_path: Path, first: str
) -> None:
    subject, spy = policy_rig(synthetic_tool(tmp_path), first, SEARCH_CALL, MODEL_TEXT)
    result = subject.run([UserMessage(COMPOUND)])
    assert result.answer == WARRANTY
    assert internal_of(result)["reply_source"] == "code"
    assert len(spy.calls) == 1
    assert subject.tool.calls == []
    assert subject.handoff.calls == []
    assert f'"code": "{InvalidCode.ONE_SEARCH_AT_A_TIME}"' in subject.prompt_text(1)
    assert len(subject.model.prompts) == 2


def test_two_different_searches_followed_by_free_text_never_reach_the_customer(
    tmp_path: Path,
) -> None:
    subject, spy = policy_rig(synthetic_tool(tmp_path), TWO_SEARCHES, TWO_SEARCHES, MODEL_TEXT)
    result = subject.run([UserMessage(COMPOUND)])
    assert result.fallback_reason is FallbackReason.INVALID_TOOL_CALL
    assert spy.calls == []
    assert MODEL_TEXT not in result.answer
    assert internal_of(result)["reply_source"] == "fallback"


def test_the_same_search_twice_in_one_block_is_one_call_and_code_speaks(tmp_path: Path) -> None:
    subject, spy = policy_rig(synthetic_tool(tmp_path), SEARCH_CALL + SEARCH_CALL, MODEL_TEXT)
    result = subject.run([UserMessage(ASKED)])
    assert result.answer == WARRANTY
    assert len(spy.calls) == 1
    assert internal_of(result)["reply_source"] == "code"


def test_a_successful_search_ends_the_turn_so_the_model_gets_no_second_word(
    tmp_path: Path,
) -> None:
    subject, _ = policy_rig(synthetic_tool(tmp_path), SEARCH_CALL, MODEL_TEXT)
    result = subject.run([UserMessage(ASKED)])
    assert len(subject.model.prompts) == 1
    assert MODEL_TEXT not in result.answer
    assert json.loads(internal_of(result)["tool_calls"][0]["result"])["status"] == "policy_found"
