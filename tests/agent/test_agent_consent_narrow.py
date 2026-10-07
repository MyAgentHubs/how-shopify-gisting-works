from typing import Any

import pytest
from agent_support import QUESTION, SESSION, Rig, internal_of, rig, tool_call

from gisting.agent.consent import agreed_offer, consent_given, offered
from gisting.agent.policy import FallbackReason, load_agent_policy
from gisting.prompt.messages import AssistantMessage, Message, UserMessage
from gisting.prompt.phrases import load_phrases
from gisting.prompt.replies import fixed_reply

POLICY = load_agent_policy()
PHRASES = load_phrases()
GUARD = POLICY.consent_guards["handoff_to_human"]
OFFERING_FALLBACKS = {FallbackReason.UNRENDERABLE_ORDER, FallbackReason.POLICY_UNAVAILABLE}
REMINDER_GUARD = POLICY.consent_guards["send_shipping_reminder"]
OFFER = PHRASES.handoff_offer
REMINDER_OFFER = PHRASES.sentences["reminder_offer"]


def field(value: str | None) -> dict[str, Any]:
    return {"value": value, "source": "shopify"}


def parcel(status: str, tracking: str | None = "TP-1") -> dict[str, Any]:
    return {
        "transport_status": field(status),
        "carrier": field("Test Parcel" if tracking else None),
        "tracking_number": field(tracking),
        "estimated_delivery": field("2026-10-05T10:00:00Z"),
        "delivered_at": field(None),
        "updated_at": field("2026-10-01T09:00:00Z"),
    }


def found(fulfillment: str, *parcels: dict[str, Any]) -> dict[str, Any]:
    order = {"fulfillment_status": field(fulfillment), "shipments": list(parcels)}
    return {"status": "found", "order": order}


OFFERS = {
    "several_parcels": fixed_reply(PHRASES, found("FULFILLED", *[parcel("IN_TRANSIT")] * 4)),
    "delayed_line": fixed_reply(PHRASES, found("FULFILLED", parcel("DELAYED"))),
    "attempted_line": fixed_reply(PHRASES, found("FULFILLED", parcel("ATTEMPTED_DELIVERY"))),
    "no_tracking_line": fixed_reply(PHRASES, found("FULFILLED", parcel("FULFILLED", None))),
    "unavailable": PHRASES.failure_replies["unavailable"],
    "locked": PHRASES.failure_replies["locked"],
}
POLITE_BRUSH_OFFS = [
    "okay thanks",
    "ok thank you",
    "yeah whatever",
    "sure thanks",
    "fine",
    "ok cool thanks",
    "yes thanks anyway",
    "ok, thx",
    "Okay. Thanks!",
    "ok never mind",
    "sure, later",
]
NOT_AGREEMENT = [
    *POLITE_BRUSH_OFFS,
    "Please send me the details of each parcel",
    "ok which parcel is delayed?",
    "Ok, what is in the first parcel?",
    "sure, but first tell me the tracking numbers",
    "please list them anyway",
    "go ahead and list all of them",
    "is this a human?",
    "is this a human",
    "agent?",
    "yes?",
    "ok, where is it?",
    "please check again",
    "sure, show me the parcel",
]
AGREEMENT = [
    "yes",
    "Yes please.",
    "ok",
    "sure",
    "yes, connect me",
    "please do",
    "human please",
    "a human",
    "agent",
]


def after(offer: str, reply: str) -> list[Message]:
    return [UserMessage(QUESTION), AssistantMessage(offer), UserMessage(reply)]


def blocked(subject: Rig, history: list[Message]) -> None:
    result = subject.run(history)
    assert subject.handoff.calls == []
    assert result.answer == OFFER
    assert internal_of(result)["guard"]["events"][0]["status"] == "needs_customer_consent"


@pytest.mark.parametrize("name", list(OFFERS))
@pytest.mark.parametrize("reply", NOT_AGREEMENT)
def test_a_question_or_a_real_request_after_an_offer_is_not_agreement(
    name: str, reply: str
) -> None:
    history = after(OFFERS[name], reply)
    assert offered(GUARD, OFFERS[name])
    assert not agreed_offer(GUARD, history)
    assert not consent_given(GUARD, history)
    blocked(rig(tool_call("handoff_to_human"), "unused"), history)


@pytest.mark.parametrize("name", list(OFFERS))
@pytest.mark.parametrize("reply", AGREEMENT)
def test_a_plain_yes_after_an_offer_is_agreement(name: str, reply: str) -> None:
    history = after(OFFERS[name], reply)
    assert agreed_offer(GUARD, history)
    assert consent_given(GUARD, history)
    subject = rig()
    subject.run(history)
    assert len(subject.handoff.calls) == 1
    assert subject.model.prompts == []


@pytest.mark.parametrize("reply", ["yes", "Yes please.", "ok", "please do", "sure"])
@pytest.mark.parametrize(
    "reason",
    [reason for reason in FallbackReason if reason not in OFFERING_FALLBACKS],
)
def test_a_yes_after_a_fallback_reply_is_not_agreement_because_a_fallback_offers_nothing(
    reason: FallbackReason, reply: str
) -> None:
    text = POLICY.fallback_replies[reason]
    assert not offered(GUARD, text)
    assert not agreed_offer(GUARD, after(text, reply))
    assert not consent_given(GUARD, after(text, reply))


@pytest.mark.parametrize(
    "reply",
    ["I want a human agent", "Yes, I want to talk to a person.", "Please connect me to a human"],
)
def test_a_customer_who_asks_for_a_human_himself_needs_no_offer(reply: str) -> None:
    assert consent_given(GUARD, [UserMessage(reply)])


@pytest.mark.parametrize(
    "said",
    ["Would you like a human agent?", "Our human agent will call you.", "ask for a human agent"],
)
def test_the_words_human_agent_in_other_text_are_not_an_offer(said: str) -> None:
    assert not offered(GUARD, said)
    assert not agreed_offer(GUARD, after(said, "yes"))


def test_only_the_exact_sentence_from_the_data_is_the_handoff_offer() -> None:
    assert offered(GUARD, f"Sorry about that. {OFFER}")
    assert not offered(GUARD, "Would you like me to connect you with a human agent?")
    assert not offered(GUARD, REMINDER_OFFER)


REMINDER_NOT = [
    *POLITE_BRUSH_OFFS,
    "Please send me the details of each parcel",
    "ok which parcel is delayed?",
    "yes but first tell me the carrier",
    "please remind me of the carrier",
    "is this a reminder?",
    "remind?",
    "go ahead and list all of them",
    "please list them anyway",
]
REMINDER_YES = ["yes", "Yes please.", "ok", "sure", "please do", "Go ahead", "send the reminder"]
ASKED = f"Your order has not shipped yet, so I do not have a delivery date. {REMINDER_OFFER}"


@pytest.mark.parametrize("reply", REMINDER_NOT)
def test_the_reminder_consent_is_as_narrow_as_the_handoff_consent(reply: str) -> None:
    history = after(ASKED, reply)
    assert not agreed_offer(REMINDER_GUARD, history)
    assert not consent_given(REMINDER_GUARD, history)


@pytest.mark.parametrize("reply", REMINDER_YES)
def test_a_plain_yes_to_the_reminder_offer_still_counts(reply: str) -> None:
    history = after(ASKED, reply)
    assert agreed_offer(REMINDER_GUARD, history)
    subject = rig()
    subject.run(history)
    assert subject.reminder.calls == [({"order_number": "#1042"}, SESSION)]


def test_a_brush_off_is_left_to_the_model_which_cannot_start_the_handoff_by_itself() -> None:
    history = after(OFFERS["delayed_line"], "okay thanks")
    subject = rig("You are welcome!")
    result = subject.run(history)
    assert subject.handoff.calls == []
    assert result.answer == "You are welcome!"


def test_a_brush_off_is_left_to_the_model_which_cannot_start_the_reminder_by_itself() -> None:
    subject = rig("You are welcome!")
    result = subject.run(after(ASKED, "ok thank you"))
    assert subject.reminder.calls == []
    assert result.answer == "You are welcome!"


@pytest.mark.parametrize("reply", ["Yes, thanks, please connect me to a human", "human please"])
def test_a_clear_request_for_a_human_still_counts_when_the_customer_is_polite(reply: str) -> None:
    assert consent_given(GUARD, after(OFFERS["delayed_line"], reply))


def test_a_shipped_parcel_with_a_tracking_number_makes_no_offer_so_a_yes_starts_nothing() -> None:
    tracked = fixed_reply(PHRASES, found("FULFILLED", parcel("FULFILLED")))
    assert not offered(GUARD, tracked)
    assert not agreed_offer(GUARD, after(tracked, "yes"))
    blocked(rig(tool_call("handoff_to_human"), "unused"), after(tracked, "yes"))
