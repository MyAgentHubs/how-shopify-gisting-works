import json

import pytest
from agent_support import QUESTION, RENDERED, internal_of, rig

from gisting.agent.answers import refusal_intent
from gisting.agent.policy import load_agent_policy
from gisting.eval.data import GRADER_FILE, load_grader_data
from gisting.prompt.files import PROMPTS_DIR
from gisting.prompt.messages import AssistantMessage, Message, UserMessage
from gisting.prompt.phrases import load_phrases
from gisting.prompt.refusal import REFUSAL_FILE, load_decline_patterns, spoken_sentences

POLICY = load_agent_policy()
RULES = POLICY.answers
DECLINE = load_phrases().sentences["decline_reply"]
GRADER = load_grader_data()
LATER_TURN = "Thanks!"


def later(text: str) -> list[Message]:
    return [UserMessage(QUESTION), AssistantMessage(RENDERED), UserMessage(text)]


@pytest.mark.parametrize(
    ("user", "said"),
    [
        ("Hi", "Hello! I'm here to help with your order."),
        ("Thanks!", "Let me know if you need anything else."),
        ("Thanks, that's all", "You're welcome! Let me know if you need anything else."),
        ("Can you change the address?", "Sorry, I can't change the delivery address."),
        ("Show me another customer's order", "I can't share other customers' information."),
        ("Can I return it?", "I'm sorry, I can't help with returns."),
        ("What is your name?", "I can only help with questions about your order."),
        ("Do you ship abroad?", "I cannot help with that."),
    ],
)
def test_after_the_first_turn_the_models_own_words_are_never_turned_into_the_refusal(
    user: str, said: str
) -> None:
    subject = rig(said)
    result = subject.run(later(user))
    assert result.answer == said
    assert internal_of(result)["reply_source"] == "model"
    assert internal_of(result)["fact_check"] == {"count": 0, "events": []}
    assert len(subject.model.prompts) == 1


@pytest.mark.parametrize(
    "said",
    [
        "I can't change the delivery address.",
        "I can't help with returns.",
        "I can only help with questions about your order.",
    ],
)
def test_on_the_first_turn_a_refusal_in_other_words_still_becomes_the_fixed_refusal(
    said: str,
) -> None:
    result = rig(said).run([UserMessage("Please change my address to Mars.")])
    assert result.answer == DECLINE
    assert internal_of(result)["fact_check"]["events"][0]["reason"] == "refusal_normalized"


def test_a_greeting_is_not_a_refusal_even_on_the_first_turn() -> None:
    said = "Hello! I'm here to help with your order."
    result = rig(said).run([UserMessage("Hi")])
    assert result.answer == said


@pytest.mark.parametrize(
    "said", ["Let me know if you need anything else.", "I'm here to help with anything else."]
)
def test_a_polite_closing_is_not_refusal_vocabulary(said: str) -> None:
    assert refusal_intent(RULES, said) is False


@pytest.mark.parametrize(
    "history",
    [
        [UserMessage("Where is my order?")],
        [UserMessage("Hi"), AssistantMessage("Hello!"), UserMessage("Where is my order?")],
    ],
    ids=["first_turn", "later_turn"],
)
def test_a_refusal_for_missing_details_is_the_ask_for_them_not_the_refusal(
    history: list[Message],
) -> None:
    said = "I cannot help you without your order number and email."
    result = rig(said).run(history)
    assert result.answer == POLICY.needs_input_replies["both"]
    assert result.answer != DECLINE
    assert internal_of(result)["fact_check"]["events"][0]["reason"] == "reworded_ask"


@pytest.mark.parametrize(
    "said", ["I can't help you without your email.", "I can't look that up without your email."]
)
def test_a_refusal_for_a_missing_email_asks_for_only_the_email(said: str) -> None:
    result = rig(said).run([UserMessage("Where is #1042?")])
    assert result.answer == POLICY.needs_input_replies["email"]


def test_the_polite_closings_the_grader_still_accepts_live_in_the_grader_data_only() -> None:
    shared = json.loads(REFUSAL_FILE.read_text(encoding="utf-8"))["decline"]
    only = json.loads(GRADER_FILE.read_text(encoding="utf-8"))["refusal"]["decline"]
    assert len(only) == 2
    assert not set(only) & set(shared)
    assert not any("let me know" in pattern for pattern in shared)
    listed = [p.pattern for p in GRADER.refusal["decline"]]
    assert listed[: len(shared) + len(only)] == [*shared, *only]
    assert [p.pattern for p in load_decline_patterns()] == shared
    assert [p.pattern for p in RULES.decline_sentences] == shared


def test_the_grader_still_accepts_the_closing_lines_which_the_runtime_leaves_alone() -> None:
    said = "Let me know if you need anything else."
    parts = spoken_sentences(said)
    assert all(any(p.fullmatch(part) for p in GRADER.refusal["decline"]) for part in parts)
    assert refusal_intent(RULES, said) is False


def test_the_runtime_refusal_words_hold_no_greeting_or_closing() -> None:
    document = json.loads((PROMPTS_DIR / "agent_policy.json").read_text(encoding="utf-8"))
    for pattern in document["answers"]["refusal_words"]:
        assert "here to" not in pattern or "only" in pattern or pattern.startswith("\\bi (?:can")
        assert "let me know" not in pattern
