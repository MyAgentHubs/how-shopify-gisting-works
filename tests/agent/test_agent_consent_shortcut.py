import pytest
from agent_support import rig, tool_call
from test_agent_consent_narrow import OFFERS, after

from gisting.agent.consent import agreed_offer, consent_given
from gisting.agent.policy import load_agent_policy

GUARD = load_agent_policy().consent_guards["handoff_to_human"]
OFFER = OFFERS["unavailable"]
SAYS_SOMETHING_ELSE = [
    "maybe later I might talk to a human",
    "should I talk to a human or wait",
    "if I wanted to talk to a human I would say so",
    "connect me to my order",
    "I can talk to someone else about it",
]
REQUESTS_BUT_NOT_PLAIN = ["Yes, I'd like to talk to someone."]


@pytest.mark.parametrize("reply", [*SAYS_SOMETHING_ELSE, *REQUESTS_BUT_NOT_PLAIN])
def test_a_sentence_that_only_contains_a_request_pattern_does_not_take_the_shortcut(
    reply: str,
) -> None:
    history = after(OFFER, reply)
    assert not agreed_offer(GUARD, history)
    subject = rig("Let me look into that.")
    subject.run(history)
    assert subject.handoff.calls == []
    assert len(subject.model.prompts) == 1


@pytest.mark.parametrize("reply", REQUESTS_BUT_NOT_PLAIN)
def test_the_model_may_still_call_the_handoff_when_the_customer_asked_in_words(reply: str) -> None:
    history = after(OFFER, reply)
    assert consent_given(GUARD, history)
    subject = rig(tool_call("handoff_to_human"), "unused")
    subject.run(history)
    assert len(subject.handoff.calls) == 1
