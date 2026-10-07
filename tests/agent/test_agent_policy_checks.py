import json

import pytest
from agent_support import rig
from synthetic_kb import ASKED, WARRANTY

from gisting.agent.checks import check_answer
from gisting.agent.state import TurnState
from gisting.prompt.messages import AssistantMessage, Message, ToolCall, ToolMessage, UserMessage

SEARCHED: list[Message] = [
    UserMessage(ASKED),
    AssistantMessage("", (ToolCall("search_policy", {"query": "zorblax warranty"}),)),
    ToolMessage(
        json.dumps({
            "status": "policy_found",
            "hits": [{"id": "kb-zz-warranty", "answer": WARRANTY}],
        })
    ),
]
REPEATED: list[Message] = [
    UserMessage(ASKED),
    AssistantMessage(WARRANTY),
    UserMessage("Could you say that again?"),
]


def vetted(messages: list[Message], text: str) -> tuple[str, list[str]]:
    state = TurnState(list(messages))
    done = check_answer(rig().deps, state, text)
    return done.answer, [check.reason for check in state.recorder.fact_checks]


def test_policy_text_with_a_weekday_a_duration_and_a_long_number_needs_its_support() -> None:
    answer, reasons = vetted([UserMessage(ASKED)], WARRANTY)
    assert answer != WARRANTY
    assert reasons[0] == "unsupported_time_claim"


def test_model_text_repeating_the_text_of_a_search_result_of_this_turn_passes_unchanged() -> None:
    assert vetted(SEARCHED, WARRANTY) == (WARRANTY, [])


def test_model_text_repeating_an_earlier_code_rendered_policy_answer_passes_unchanged() -> None:
    assert vetted(REPEATED, WARRANTY) == (WARRANTY, [])


@pytest.mark.parametrize("invented", ["It lasts 24 months.", "Claims are answered by Tuesday."])
def test_a_figure_or_day_the_policy_text_does_not_hold_is_still_caught(invented: str) -> None:
    answer, reasons = vetted(SEARCHED, invented)
    assert answer != invented
    assert reasons[0] == "unsupported_time_claim"
