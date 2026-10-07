import json
from pathlib import Path
from typing import Any

import pytest
from agent_support import good_call, internal_of, rig

from gisting.agent.answers import refusal_intent
from gisting.agent.policy import load_agent_policy
from gisting.eval.data import GRADER_FILE, load_grader_data
from gisting.prompt.messages import UserMessage
from gisting.prompt.phrases import load_phrases
from gisting.prompt.refusal import REFUSAL_FILE, load_decline_patterns, spoken_sentences
from gisting.prompt.replies import fixed_reply

PHRASES = load_phrases()
POLICY = load_agent_policy()
RULES = POLICY.answers
DECLINE = PHRASES.sentences["decline_reply"]
CORPUS = Path(__file__).resolve().parents[1] / "eval" / "corpus" / "known_good.json"
GRADER = load_grader_data()
JOKES = [
    "I can't tell jokes.",
    "Sorry, I am unable to write poems.",
    "Unfortunately I can't do math problems",
    "I'm sorry, I can’t reveal that.",
]
OTHER_WORDS = [
    "I cannot answer that question. I only know about order status and shipping.",
    "I am unable to provide information about holiday schedules, sorry.",
    "I cannot provide any information on that topic here.",
    "Sorry, I can't discuss that topic with you today.",
    "I only know about orders and deliveries at this store.",
    "That is outside what I do. I only know about your parcel.",
]
NOT_REFUSALS = [
    "I cannot find your order.",
    "I can't find an order with those details.",
    "I cannot see any tracking for it.",
    "You're welcome! Let me know if you need anything else.",
    "Hello! How can I help?",
]


def leaf(value: str) -> dict[str, str]:
    return {"value": value, "source": "shopify"}


def parcel(status: str, tracking: str) -> dict[str, Any]:
    return {
        "transport_status": leaf(status),
        "carrier": leaf("Test Parcel"),
        "tracking_number": leaf(tracking),
        "estimated_delivery": leaf("2026-10-05T10:00:00Z"),
        "delivered_at": {"value": None, "source": "shopify"},
    }


def customer_visible_texts() -> list[str]:
    sentences = {k: v for k, v in PHRASES.sentences.items() if k != "decline_reply"}
    texts = [*sentences.values(), *PHRASES.failure_replies.values(), *PHRASES.ask.values()]
    texts += [*PHRASES.ask_bare.values(), *POLICY.fallback_replies.values()]
    texts += [*POLICY.needs_input_replies.values(), *POLICY.needs_consent_replies.values()]
    parcels = PHRASES.parcels
    texts += [parcels.many_reply, *parcels.status.values(), *parcels.missing.values()]
    texts += [text for facts in parcels.facts.values() for text in facts.values()]
    texts += [t for table in PHRASES.reply_by_status.values() for t in table.values()]
    return texts


def test_the_runtime_and_the_grader_load_the_same_decline_list_from_one_data_file() -> None:
    document = json.loads(REFUSAL_FILE.read_text(encoding="utf-8"))
    listed = [p.pattern for p in load_decline_patterns()]
    assert listed == document["decline"]
    assert [p.pattern for p in RULES.decline_sentences] == listed
    own = json.loads(GRADER_FILE.read_text(encoding="utf-8"))["refusal"]["decline"]
    assert [p.pattern for p in GRADER.refusal["decline"]][: len(listed) + len(own)] == [
        *listed,
        *own,
    ]


@pytest.mark.parametrize("said", JOKES)
def test_a_first_turn_refusal_the_grader_accepts_becomes_the_fixed_refusal(said: str) -> None:
    result = rig(said).run([UserMessage("Tell me a joke.")])
    assert result.answer == DECLINE
    event = internal_of(result)["fact_check"]["events"][0]
    assert event["reason"] == "refusal_normalized"
    assert internal_of(result)["reply_source"] == "template"


@pytest.mark.parametrize("said", OTHER_WORDS)
def test_a_refusal_that_says_it_cannot_answer_or_only_knows_about_orders_becomes_the_fixed_refusal(
    said: str,
) -> None:
    assert refusal_intent(RULES, said) is True
    result = rig(said).run([UserMessage("Tell me a joke.")])
    assert result.answer == DECLINE
    assert internal_of(result)["fact_check"]["events"][0]["reason"] == "refusal_normalized"
    assert internal_of(result)["reply_source"] == "template"


@pytest.mark.parametrize("said", OTHER_WORDS)
def test_that_refusal_in_other_words_to_an_order_question_still_becomes_the_ask(said: str) -> None:
    result = rig(said).run([UserMessage("Where is my parcel?")])
    assert result.answer == POLICY.needs_input_replies["both"]


@pytest.mark.parametrize("said", NOT_REFUSALS)
def test_an_answer_that_only_sounds_negative_is_left_alone(said: str) -> None:
    assert refusal_intent(RULES, said) is False
    assert rig(said).run([UserMessage("hi")]).answer == said


def test_a_failure_reply_in_the_models_words_is_not_a_refusal() -> None:
    assert (
        refusal_intent(RULES, "I couldn't find an order matching that order number and email.")
        is False
    )


@pytest.mark.parametrize("said", customer_visible_texts())
def test_no_customer_visible_sentence_in_the_data_is_taken_for_a_refusal(said: str) -> None:
    assert refusal_intent(RULES, said) is False


def test_every_rendered_found_line_and_failure_reply_is_not_taken_for_a_refusal() -> None:
    parcels = [parcel("IN_TRANSIT", "TP-1"), parcel("DELAYED", "TP-2")]
    order = {"fulfillment_status": leaf("FULFILLED"), "shipments": parcels}
    rendered = [fixed_reply(PHRASES, {"status": "found", "order": order})]
    rendered += [fixed_reply(PHRASES, {"status": status}) for status in PHRASES.failure_replies]
    assert not any(refusal_intent(RULES, text) for text in rendered)


def accepted_decline_outputs() -> list[dict[str, Any]]:
    found_here: list[dict[str, Any]] = []
    for entry in json.loads(CORPUS.read_text(encoding="utf-8")):
        if entry.get("kind", "first") != "first" or entry["category"] not in (
            "offtopic",
            "injection",
        ):
            continue
        parts = spoken_sentences(entry["output"])
        if parts and all(any(p.fullmatch(s) for p in GRADER.refusal["decline"]) for s in parts):
            found_here.append(entry)
    return found_here


def test_the_corpus_has_refusals_to_check() -> None:
    assert len(accepted_decline_outputs()) >= 5


@pytest.mark.parametrize("entry", accepted_decline_outputs(), ids=lambda e: e["id"])
def test_whatever_the_grader_accepts_as_a_refusal_the_runtime_replaces(
    entry: dict[str, Any],
) -> None:
    assert refusal_intent(RULES, entry["output"]) is True


def test_a_turn_with_a_tool_result_is_never_replaced_by_the_refusal() -> None:
    subject = rig(good_call(), "I cannot help with that.")
    result = subject.run()
    assert result.answer != DECLINE
    assert result.answer.startswith("Your order is on its way.")
    assert internal_of(result)["fact_check"]["count"] == 0


def test_a_refusal_in_other_words_to_an_order_question_still_becomes_the_ask() -> None:
    result = rig("I can't tell you that.").run([UserMessage("Where is my parcel?")])
    assert result.answer == POLICY.needs_input_replies["both"]
    assert internal_of(result)["fact_check"]["events"][-1]["reason"] == "refusal_on_order_question"


@pytest.mark.parametrize(
    "said",
    ["I'm unable to help with that.", "I’m not able to assist with that.", "I'm unable to answer."],
)
def test_a_contracted_unable_or_not_able_refusal_is_recognised(said: str) -> None:
    assert refusal_intent(RULES, said) is True
