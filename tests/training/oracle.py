import json

from gisting.agent.guard import ask_reply, unprovided_inputs, user_texts
from gisting.agent.policy import Grounding, load_agent_policy
from gisting.prompt.messages import AssistantMessage, ToolMessage
from gisting.prompt.phrases import load_phrases
from gisting.prompt.replies import fixed_reply
from gisting.training.samples import Sample

POLICY = load_agent_policy()
PHRASES = load_phrases()
DECLINE = "Sorry, I can only help with order and delivery questions at Gisting Lab Store."
SKIPPED = "Okay, no problem."
DECLINES = {"handoff_decline", "reminder_decline"}
POLICY_CATEGORIES = {"policy_question", "policy_outside_kb"}


def written_order(sample: Sample) -> str:
    first = sample.messages[0].content
    found = POLICY.patterns[Grounding.ORDER_NUMBER].search(first)
    assert found is not None
    return found.group(0)


def tool_call(name: str, **arguments: object) -> str:
    return f"<tool_call>\n{json.dumps({'name': name, 'arguments': arguments})}\n</tool_call>"


def first_turn(sample: Sample) -> str:
    category = sample.category
    if category == "order_full":
        return tool_call("lookup_order", order_number=written_order(sample), email=sample.email)
    if category in ("order_no_email", "order_no_number"):
        return ask_reply(POLICY, unprovided_inputs(POLICY, user_texts(sample.messages)))
    if category == "handoff_request":
        return tool_call("handoff_to_human")
    if category in POLICY_CATEGORIES:
        return tool_call("search_policy", query=user_texts(sample.messages)[-1])
    return SKIPPED if category in DECLINES else DECLINE


def second_turn(sample: Sample) -> str:
    last = sample.messages[-1]
    assert isinstance(last, ToolMessage)
    return fixed_reply(PHRASES, json.loads(last.content))


def expected_output(sample: Sample) -> str:
    if sample.kind == "second":
        return second_turn(sample)
    return first_turn(sample)


def last_assistant_text(sample: Sample) -> str:
    texts = [m.content for m in sample.messages if isinstance(m, AssistantMessage) and m.content]
    return texts[-1] if texts else ""
