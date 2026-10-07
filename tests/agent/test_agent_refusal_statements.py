import pytest
from agent_support import internal_of, rig

from gisting.agent.answers import refusal_intent
from gisting.agent.policy import load_agent_policy
from gisting.eval.data import load_grader_data
from gisting.prompt.messages import AssistantMessage, Message, UserMessage
from gisting.prompt.phrases import load_phrases
from gisting.prompt.refusal import is_decline

POLICY = load_agent_policy()
RULES = POLICY.answers
DECLINE = load_phrases().sentences["decline_reply"]
GRADER = load_grader_data()
SCOPE_STATEMENTS = [
    "Hello! I'm just here to help with your order and delivery. How can I assist you today?",
    "Sorry, I can only answer order and delivery related questions.",
    "Sorry, I can't reset your configuration. "
    "I'm here to help you with order and delivery questions.",
    "Sorry, I can only order food and drinks from Gisting Lab Store.",
    "I can only discuss order and delivery topics.",
    "I’m only here to help with delivery.",
]
LEFT_ALONE = [
    "I can only look up one order at a time. Which one would you like first?",
    "Sorry, I can only connect you to a human agent if you say yes to my offer of one.",
    "I can only see the status of an order once you send the order number.",
    "Hello! I'm here to help with your order.",
    "Hello! I'm here to help with your order and delivery questions. What can I do for you?",
    "Hi there, how can I help you today?",
    "You're welcome! Let me know if you need anything else.",
]


@pytest.mark.parametrize("said", SCOPE_STATEMENTS)
def test_a_first_turn_scope_statement_in_the_models_words_becomes_the_fixed_refusal(
    said: str,
) -> None:
    result = rig(said).run([UserMessage("Tell me a joke.")])
    assert result.answer == DECLINE
    assert internal_of(result)["fact_check"]["events"][0]["reason"] == "refusal_normalized"
    assert internal_of(result)["reply_source"] == "template"


@pytest.mark.parametrize("said", LEFT_ALONE)
def test_a_greeting_or_closing_without_just_or_only_is_left_alone(said: str) -> None:
    assert refusal_intent(RULES, said) is False
    assert rig(said).run([UserMessage("Hi")]).answer == said


@pytest.mark.parametrize("said", SCOPE_STATEMENTS)
def test_a_scope_statement_after_the_first_turn_is_never_replaced(said: str) -> None:
    history: list[Message] = [UserMessage("Hi")]
    subject = rig("Hello!", said)
    first = subject.run(history)
    assert first.answer == "Hello!"
    later = subject.run([*history, AssistantMessage("Hello!"), UserMessage("Tell me a joke")])
    assert later.answer == said


@pytest.mark.parametrize("said", SCOPE_STATEMENTS)
def test_the_grader_does_not_accept_a_scope_statement_the_runtime_replaces(said: str) -> None:
    assert not is_decline(GRADER.refusal["decline"], said)
