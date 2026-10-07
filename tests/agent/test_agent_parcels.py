import pytest
from agent_support import QUESTION, SESSION, internal_of, rig

from gisting.prompt.messages import AssistantMessage, Message, UserMessage
from gisting.prompt.phrases import load_phrases
from gisting.tools.handoff import SPEC as HANDOFF
from gisting.tools.mock import load_reference_policy, reference_for

PHRASES = load_phrases()
S = PHRASES.sentences
SEVERAL = PHRASES.parcels.many_reply
TICKET = reference_for(SESSION, load_reference_policy(HANDOFF.policy_file))


def after(offer: str, reply: str) -> list[Message]:
    return [UserMessage(QUESTION), AssistantMessage(offer), UserMessage(reply)]


@pytest.mark.parametrize("reply", ["yes", "Yes please", "yeah, sure", "ok", "Go ahead"])
def test_a_yes_to_the_several_parcels_reply_hands_the_customer_over_in_code(reply: str) -> None:
    subject = rig()
    result = subject.run(after(SEVERAL, reply))
    assert result.answer == S["handoff_confirmation"].replace("<ticket>", TICKET)
    assert subject.handoff.calls == [({"reason": "customer_request"}, SESSION)]
    assert subject.model.prompts == []
    assert internal_of(result)["fact_check"]["events"][0]["reason"] == "agreed_offer"


@pytest.mark.parametrize("reply", ["No thanks", "no", "Not now, thanks"])
def test_a_no_to_the_several_parcels_reply_gets_the_fixed_acknowledgement(reply: str) -> None:
    subject = rig()
    result = subject.run(after(SEVERAL, reply))
    assert result.answer == S["decline_ack"]
    assert subject.handoff.calls == []


def test_the_several_parcels_reply_ends_with_the_handoff_offer_the_guard_looks_for() -> None:
    assert SEVERAL.endswith(S["handoff_offer"])
