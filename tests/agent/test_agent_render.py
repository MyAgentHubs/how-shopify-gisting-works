import json

import pytest
from agent_support import NUMBER, SESSION, good_call, internal_of, rig, tool_call

from gisting.agent.answers import lookup_reply, refusal_intent
from gisting.agent.policy import load_agent_policy
from gisting.prompt.files import PROMPTS_DIR
from gisting.prompt.messages import UserMessage
from gisting.prompt.phrases import load_phrases
from gisting.prompt.replies import Unrenderable

PHRASES = load_phrases()
RULES = load_agent_policy().answers
DECLINE = PHRASES.sentences["decline_reply"]


def test_after_a_lookup_the_answer_is_rendered_by_code_and_the_model_is_not_asked_again() -> None:
    subject = rig(good_call(), "never used")
    result = subject.run()
    assert result.answer.startswith(
        "Your order is on its way. It is with Test Parcel, tracking number TP-"
    )
    assert result.answer.endswith("Expected delivery: October 5.")
    assert subject.model.outputs == ["never used"]
    internal = internal_of(result)
    assert internal["reply_source"] == "code"
    assert len(internal["model_calls"]) == 1
    assert internal["fact_check"]["count"] == 0


def test_a_no_match_lookup_is_answered_with_the_failure_reply_from_the_data() -> None:
    other = "someone.else@example.com"
    subject = rig(tool_call(order_number=f"#{NUMBER}", email=other), "never used")
    result = subject.run([UserMessage(f"Where is #{NUMBER}? {other}")])
    assert result.answer == PHRASES.failure_replies["no_match"]
    assert internal_of(result)["reply_source"] == "code"


def test_a_locked_lookup_is_answered_with_the_locked_reply() -> None:
    subject = rig(good_call(), "never used")
    for _ in range(10):
        subject.attempts.record_failure(SESSION)
    result = subject.run()
    assert result.answer == PHRASES.failure_replies["locked"]


@pytest.mark.parametrize("status", ["no_match", "unavailable", "locked"])
def test_every_failure_status_has_its_reply_and_other_tools_have_none(status: str) -> None:
    assert (
        lookup_reply(RULES, "lookup_order", {"status": status}) == PHRASES.failure_replies[status]
    )
    assert lookup_reply(RULES, "handoff_to_human", {"status": status}) is None
    assert isinstance(
        lookup_reply(RULES, "lookup_order", {"status": "invalid_tool_call"}), Unrenderable
    )


def test_the_model_text_after_the_tool_never_reaches_the_customer() -> None:
    subject = rig(good_call(), "Your order has been delivered. Have a great day!")
    assert "delivered" not in subject.run().answer.lower().replace("expected delivery", "")


@pytest.mark.parametrize(
    "said",
    [
        "I cannot help with that, but I can look up an order.",
        "Sorry, I can't assist with that request.",
        "I can only help with orders and delivery.",
        "I'm here to help with orders and delivery only.",
        "Unfortunately I am unable to help with that.",
    ],
)
def test_a_refusal_in_the_models_own_words_becomes_the_fixed_refusal(said: str) -> None:
    result = rig(said).run([UserMessage("Tell a joke.")])
    assert result.answer == DECLINE
    event = internal_of(result)["fact_check"]["events"][0]
    assert event["reason"] == "refusal_normalized"


def test_the_fixed_refusal_itself_is_not_flagged_as_rewritten() -> None:
    result = rig(DECLINE).run([UserMessage("Tell a joke.")])
    assert result.answer == DECLINE
    assert internal_of(result)["fact_check"]["count"] == 0


def test_a_refusal_in_other_words_to_an_order_question_still_becomes_the_ask() -> None:
    said = "I cannot help with that."
    result = rig(said).run([UserMessage("Where is my parcel?")])
    assert result.answer == load_agent_policy().needs_input_replies["both"]
    assert internal_of(result)["fact_check"]["events"][-1]["reason"] == "refusal_on_order_question"


@pytest.mark.parametrize(
    "said", ["I cannot find your order.", "Hello! How can I help?", "Your email is wrong.", "Okay."]
)
def test_an_answer_that_is_not_a_refusal_is_left_alone(said: str) -> None:
    assert refusal_intent(RULES, said) is False
    result = rig(said).run([UserMessage("hi")])
    assert result.answer == said


def test_the_refusal_vocabulary_is_data() -> None:
    document = json.loads((PROMPTS_DIR / "agent_policy.json").read_text(encoding="utf-8"))
    listed = document["answers"]["refusal_words"]
    assert [p.pattern for p in RULES.refusal_words] == listed
