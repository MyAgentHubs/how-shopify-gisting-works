import json

from agent_support import EMAIL, SECRET
from synthetic_kb import ASKED, NO_MATCH_REPLY, OFF_TOPIC, WARRANTY, worded

from gisting.agent.context import without_earlier_orders
from gisting.agent.policy import load_agent_policy
from gisting.prompt.messages import AssistantMessage, Message, ToolCall, ToolMessage, UserMessage
from gisting.prompt.phrases import load_phrases
from gisting.shopify.demo_email import demo_email
from gisting.tools.policy import load_policy

POLICY = worded(load_agent_policy())
LOOKUP = load_policy()
ANSWERS = frozenset({WARRANTY})
ASK_A = f"Where is order #1042? My email is {EMAIL}"
ASK_B = f"And order #1043? My email is {demo_email(SECRET, '#1043')}"
STATUS_LINE = (
    "Your order is on its way. It is with Test Parcel, tracking number TP-1042. "
    "Expected delivery: October 5."
)
NO_ORDER = load_phrases().failure_replies["no_match"]
FOUND_POLICY = json.dumps({"status": "policy_found", "hits": [{"id": "kb-zz-warranty"}]})


def cleaned(history: list[Message], answers: frozenset[str] = ANSWERS) -> list[Message]:
    return without_earlier_orders(POLICY, LOOKUP, history, answers).messages


def test_a_policy_answer_in_an_armed_segment_is_not_taken_for_shown_order_facts() -> None:
    history: list[Message] = [
        UserMessage(ASK_A),
        AssistantMessage(NO_ORDER),
        UserMessage(ASKED),
        AssistantMessage(WARRANTY),
        UserMessage(ASK_B),
    ]
    result = without_earlier_orders(POLICY, LOOKUP, history, ANSWERS)
    assert result.messages == history
    assert (result.removed, result.segments) == (0, 0)


def test_the_no_match_reply_is_not_taken_for_shown_order_facts() -> None:
    history: list[Message] = [
        UserMessage(ASK_A),
        AssistantMessage(NO_ORDER),
        UserMessage(OFF_TOPIC),
        AssistantMessage(NO_MATCH_REPLY),
        UserMessage(ASK_B),
    ]
    assert cleaned(history) == history


def test_a_policy_search_result_carries_no_order_number_so_it_shows_no_facts() -> None:
    history: list[Message] = [
        UserMessage(ASK_A),
        AssistantMessage("", (ToolCall("search_policy", {"query": "zorblax"}),)),
        ToolMessage(FOUND_POLICY),
        AssistantMessage(WARRANTY),
        UserMessage(ASK_B),
    ]
    assert cleaned(history) == history


def test_a_segment_that_showed_order_facts_is_still_dropped_with_its_policy_answers() -> None:
    placeholder = POLICY.dropped_placeholder
    history: list[Message] = [
        UserMessage(ASK_A),
        AssistantMessage(STATUS_LINE),
        UserMessage(ASKED),
        AssistantMessage(WARRANTY),
        UserMessage(ASK_B),
    ]
    assert cleaned(history) == [
        UserMessage(placeholder),
        AssistantMessage(placeholder),
        UserMessage(placeholder),
        AssistantMessage(placeholder),
        history[-1],
    ]


def test_without_the_known_answers_a_policy_reply_reads_as_text_that_may_hold_facts() -> None:
    history: list[Message] = [
        UserMessage(ASK_A),
        AssistantMessage(WARRANTY),
        UserMessage(ASK_B),
    ]
    assert cleaned(history, frozenset()) != history
    assert cleaned(history) == history


def test_a_policy_answer_after_the_switch_stays_in_the_new_segment() -> None:
    history: list[Message] = [
        UserMessage(ASK_A),
        AssistantMessage(STATUS_LINE),
        UserMessage(ASK_B),
        AssistantMessage(NO_ORDER),
        UserMessage(ASKED),
        AssistantMessage(WARRANTY),
        UserMessage("thanks"),
    ]
    kept = cleaned(history)
    assert kept[2:] == history[2:]
    assert all(EMAIL not in message.content for message in kept)
