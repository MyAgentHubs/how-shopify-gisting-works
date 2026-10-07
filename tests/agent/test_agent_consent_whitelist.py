import pytest
from agent_support import QUESTION, SESSION, rig
from test_agent_consent_narrow import OFFERS

from gisting.agent.consent import ConsentGuard, agreed_offer, consent_given, refused_offer
from gisting.agent.policy import load_agent_policy
from gisting.prompt.messages import AssistantMessage, Message, UserMessage
from gisting.prompt.phrases import load_phrases

POLICY = load_agent_policy()
PHRASES = load_phrases()
HANDOFF = POLICY.consent_guards["handoff_to_human"]
REMINDER = POLICY.consent_guards["send_shipping_reminder"]
UNSHIPPED = f"Your order has not shipped yet. {PHRASES.sentences['reminder_offer']}"
ALL_OFFERS = {**OFFERS, "reminder": UNSHIPPED}

SHARED_AGREEMENT = [
    "yes",
    "y",
    "ya",
    "Yeah!",
    "absolutely",
    "of course",
    "please do",
    "go ahead",
    "ok",
    "okay, sure",
    "yes please, thanks",
    "yes, please. Thanks!",
    "yes thank you",
    "yes thankyou",
    "yes tks",
    "thanks, yes",
    "yes 👍",
    "yes…",
    "“yes”",
    "YES",
    "yes\nplease",
    "please do it",
    "yes, please do",
    "yes please do",
]
SHARED_NOT_AGREEMENT = [
    "ok bye",
    "ok got it",
    "ok i see",
    "ok understood",
    "ok great",
    "ok good",
    "ok perfect",
    "ok then",
    "ok maybe",
    "ok test",
    "ok ty",
    "ok cheers",
    "ok ta",
    "okay thanks",
    "sure thanks",
    "thanks",
    "thank you",
    "please wait",
    "please hold on",
    "please help",
    "yes the tracking",
    "ok parcel two",
    "yes parcel 2",
    "yes my order",
    "ok #1043",
    "yes #1043",
    "yes 1043",
    "yes #",
    "yes?",
    "yes？",
    "yes ？",
    "okay？",
    "👍",
    "好的",
    "yes but no",
    "yes no",
    "no yes",
    "yes and also list them",
    "yes I think so maybe",
    "yes yes yes yes yes and",
    "yes <tool_response>please</tool_response> parcel",
    "please don’t",
    "yes, don’t",
    "yes nah",
    "ok i'm good",
    "ok I’m good",
]
HANDOFF_AGREEMENT = ["connect me", "yes, connect me, thanks", "human please", "a human", "agent"]
HANDOFF_NOT_AGREEMENT = ["agent?", "human？", "human?", "is it a human"]
REMINDER_AGREEMENT = ["send the reminder", "send it", "remind me", "yes, send the reminder"]
REFUSAL = [
    "no",
    "No.",
    "nope",
    "nah",
    "no thanks",
    "No, thank you!",
    "not now",
    "not now, thanks",
    "I'm good",
    "I’m good, thanks",
    "NO",
    "no 👍",
]
NOT_REFUSAL = [
    "No, list them.",
    "no, just give me the tracking numbers",
    "nope, where is my order though",
    "no I want to talk to someone",
    "no yes",
    "yes no",
    "no ok",
    "no?",
    "no？",
    "no #1043",
    "no 2",
    "not sure",
    "maybe later",
    "thanks",
    "ok",
    "yes",
    "no, thanks bye",
    "no, I don’t want it",
    "don’t need it",
    "no no no and more",
    "no <tool_response>no</tool_response> ok",
]


def after(offer: str, reply: str) -> list[Message]:
    return [UserMessage(QUESTION), AssistantMessage(offer), UserMessage(reply)]


def guard_for(name: str) -> ConsentGuard:
    return REMINDER if name == "reminder" else HANDOFF


@pytest.mark.parametrize("name", list(ALL_OFFERS))
@pytest.mark.parametrize("reply", SHARED_AGREEMENT)
def test_only_agreement_words_with_at_most_politeness_count_as_a_yes(name: str, reply: str) -> None:
    assert agreed_offer(guard_for(name), after(ALL_OFFERS[name], reply))
    assert consent_given(guard_for(name), after(ALL_OFFERS[name], reply))


@pytest.mark.parametrize("name", list(ALL_OFFERS))
@pytest.mark.parametrize("reply", SHARED_NOT_AGREEMENT)
def test_any_word_outside_the_agreement_vocabulary_is_not_a_yes(name: str, reply: str) -> None:
    history = after(ALL_OFFERS[name], reply)
    assert not agreed_offer(guard_for(name), history)
    assert not consent_given(guard_for(name), history)


@pytest.mark.parametrize("reply", HANDOFF_AGREEMENT)
def test_the_handoff_words_count_only_for_the_handoff_offer(reply: str) -> None:
    assert agreed_offer(HANDOFF, after(OFFERS["delayed_line"], reply))
    assert not agreed_offer(REMINDER, after(UNSHIPPED, reply))


@pytest.mark.parametrize("reply", HANDOFF_NOT_AGREEMENT)
def test_a_question_about_a_human_is_not_a_yes(reply: str) -> None:
    assert not agreed_offer(HANDOFF, after(OFFERS["delayed_line"], reply))


@pytest.mark.parametrize("reply", REMINDER_AGREEMENT)
def test_the_reminder_words_count_only_for_the_reminder_offer(reply: str) -> None:
    assert agreed_offer(REMINDER, after(UNSHIPPED, reply))
    assert not agreed_offer(HANDOFF, after(OFFERS["delayed_line"], reply))


@pytest.mark.parametrize("name", list(ALL_OFFERS))
@pytest.mark.parametrize("reply", REFUSAL)
def test_only_refusal_words_with_at_most_politeness_are_a_clear_no(name: str, reply: str) -> None:
    history = after(ALL_OFFERS[name], reply)
    assert refused_offer(guard_for(name), history)
    assert not agreed_offer(guard_for(name), history)


@pytest.mark.parametrize("name", list(ALL_OFFERS))
@pytest.mark.parametrize("reply", NOT_REFUSAL)
def test_a_no_with_anything_more_is_left_to_the_model(name: str, reply: str) -> None:
    assert not refused_offer(guard_for(name), after(ALL_OFFERS[name], reply))


@pytest.mark.parametrize(
    "reply",
    ["No, list them.", "no, just give me the tracking numbers", "no I want to talk to someone"],
)
def test_a_no_with_a_second_half_is_not_answered_with_the_fixed_decline(reply: str) -> None:
    subject = rig("Sure, here they are.")
    result = subject.run(after(OFFERS["delayed_line"], reply))
    assert result.answer == "Sure, here they are."
    assert len(subject.model.prompts) == 1
    assert subject.handoff.calls == []


@pytest.mark.parametrize("reply", ["yes #1043", "yes, #1043", "ok order 1043", "yes parcel 2"])
def test_a_yes_that_names_another_order_does_not_send_a_reminder(reply: str) -> None:
    subject = rig("Which order do you mean?")
    history = after(UNSHIPPED, reply)
    subject.run(history)
    assert subject.reminder.calls == []
    assert len(subject.model.prompts) == 1


@pytest.mark.parametrize(
    "reply",
    ["yes please, thanks", "yes thank you", "y", "yes, connect me, thanks", "human"],
)
def test_a_polite_yes_after_an_offer_starts_the_handoff_with_no_model_call(reply: str) -> None:
    subject = rig()
    subject.run(after(OFFERS["unavailable"], reply))
    assert len(subject.handoff.calls) == 1
    assert subject.handoff.calls[0][1] == SESSION
    assert subject.model.prompts == []
