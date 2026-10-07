import json
from pathlib import Path

import pytest

from gisting.prompt.phrases import PHRASES_FILE, PhrasesError, load_phrases, parse_phrases
from gisting.prompt.rules import rules_text

PLAN = Path(__file__).resolve().parents[2] / "data" / "demo-orders" / "shipment-plan-v1.json"
PHRASES = load_phrases()
CODE_ONLY = {"handoff_confirmation", "reminder_confirmation", "decline_ack"}


def edited(change: dict[str, object]) -> str:
    document = json.loads(PHRASES_FILE.read_text(encoding="utf-8"))
    return json.dumps({**document, **change})


def test_the_rules_render_with_no_placeholder_left() -> None:
    text = rules_text()
    assert "{" not in text
    assert "}" not in text


def test_the_call_examples_and_the_refusal_sentence_reach_the_rendered_rules() -> None:
    text = rules_text()
    assert f'reply only "{PHRASES.sentences["decline_reply"]}"' in text
    for example in PHRASES.step_examples:
        assert f'Customer: "{example.customer}"\nReply: ' in text
        assert f'order_number "{example.order_number}" and email "{example.email}"' in text


def test_the_rules_only_say_to_ask_for_what_is_missing_and_leave_the_sentences_to_the_agent() -> (
    None
):
    text = rules_text()
    assert "ask for only what is missing" in text
    for sentence in (*PHRASES.ask.values(), *PHRASES.ask_bare.values()):
        assert sentence not in text
    for value in PHRASES.ask_examples.values():
        assert value not in text


def test_the_rules_say_how_to_judge_and_never_how_to_word_a_customer_reply() -> None:
    text = rules_text()
    shown = {"decline_reply"}
    for name, sentence in PHRASES.sentences.items():
        assert (sentence in text) is (name in shown), name
    for words in (*PHRASES.fulfillment_status.values(), *PHRASES.transport_status.values()):
        assert words not in text
    for reply in PHRASES.failure_replies.values():
        assert reply not in text
    assert "Expected delivery" not in text
    assert "tracking number <" not in text


def test_the_rules_stay_short_because_code_renders_the_replies() -> None:
    assert len(rules_text()) < 3300


def test_every_ask_carries_example_values_and_the_bare_form_does_not() -> None:
    for key, sentence in PHRASES.ask.items():
        assert "(for example, " in sentence
        assert "(for example" not in PHRASES.ask_bare[key]
        assert PHRASES.ask_bare[key].endswith("?")
    for value in PHRASES.ask_examples.values():
        assert all(value not in bare for bare in PHRASES.ask_bare.values())


def test_the_example_spans_are_the_parentheses_the_asks_carry() -> None:
    for span in PHRASES.example_spans:
        assert any(span in sentence for sentence in PHRASES.ask.values())
    assert len(PHRASES.example_spans) == len(PHRASES.ask_examples)


def test_a_reply_line_naming_a_sentence_that_does_not_exist_is_rejected() -> None:
    lines = json.loads(PHRASES_FILE.read_text())["reply_by_status"]
    lines["fulfillment_status"]["UNFULFILLED"] = "Your order {words}. {no_such_sentence}"
    with pytest.raises(PhrasesError):
        parse_phrases(edited({"reply_by_status": lines}))


def test_the_call_steps_of_both_mock_tools_are_in_the_rules() -> None:
    text = rules_text()
    assert "call handoff_to_human" in text
    assert "call send_shipping_reminder" in text
    assert "reason" not in text
    assert "handed_off" not in text


def test_the_unshipped_line_offers_the_reminder_request_and_never_thanks_for_patience() -> None:
    line = PHRASES.reply_by_status["fulfillment_status"]["UNFULFILLED"]
    assert "{reminder_offer}" in line
    assert "{thanks_patience}" not in line


def test_the_rule_text_does_not_hold_the_table_copy() -> None:
    template = (PHRASES_FILE.parent / "system_rules.md").read_text(encoding="utf-8")
    for phrase in (*PHRASES.fulfillment_status.values(), *PHRASES.transport_status.values()):
        assert phrase not in template


def test_the_table_covers_every_status_the_demo_plan_can_produce() -> None:
    entries = json.loads(PLAN.read_text(encoding="utf-8"))["entries"]
    events = {entry["event"]["status"] for entry in entries if entry.get("event")}
    assert events | {"FULFILLED"} <= set(PHRASES.transport_status)
    assert set(PHRASES.fulfillment_status) == {"UNFULFILLED", "PARTIALLY_FULFILLED", "FULFILLED"}


MALFORMED: list[dict[str, object]] = [
    {"ask": {"both": "x", "email": "y"}},
    {"ask": {"both": "x", "email": "y", "order_number": 3}},
    {"ask": {"both": "x", "email": "y", "order_number": "z", "extra": "w"}},
    {"transport_status": {}},
    {"fulfillment_status": {"UNFULFILLED": " "}},
    {"reply_by_status": {}},
    {"reply_by_status": {"transport_status": {"IN_TRANSIT": "x"}}},
    {"step_examples": []},
    {"step_examples": [{"customer": "hi", "ask": "nothing"}]},
    {"step_examples": [{"customer": "hi"}]},
    {"step_examples": [{"customer": "hi", "ask": "both", "call": {}}]},
    {"step_examples": [{"customer": "hi", "call": {"order_number": "#1"}}]},
    {"sentences": {}},
    {"sentences": {"no_shipment_details": "x", "handoff_offer": "y"}},
    {"sentences": {**json.loads(PHRASES_FILE.read_text())["sentences"], "reassurance": " "}},
    {"failure_replies": {"no_match": "x"}},
    {"failure_replies": {"no_match": "x", "unavailable": "y", "locked": "z", "extra": "w"}},
    {"failure_replies": {"no_match": "x", "unavailable": "{no_such_sentence}", "locked": "z"}},
    {"empathy": []},
    {"empathy": ["no_such_sentence"]},
    {"ask_examples": {"order_number": "#1234"}},
    {"ask_example_wrapper": " (for example)"},
    {"ask": {"both": "x", "email": "y", "order_number": "z"}},
    {
        "ask": {
            "both": "Could you send me your order number{order_number_example} and the email?",
            "email": "Could you send me the email{email_example}?",
            "order_number": "Could you send me your order number{order_number_example}?",
        }
    },
    {"ask_examples": {"order_number": "#1234", "email": "name@example.com", "phone": "1"}},
]


@pytest.mark.parametrize("change", MALFORMED)
def test_malformed_reply_phrases_are_rejected(change: dict[str, object]) -> None:
    with pytest.raises(PhrasesError):
        parse_phrases(edited(change))


def test_reply_phrases_that_are_not_an_object_are_rejected() -> None:
    with pytest.raises(PhrasesError):
        parse_phrases("[]")


def test_the_failure_replies_come_from_the_data_and_end_with_the_handoff_offer() -> None:
    assert set(PHRASES.failure_replies) == {"no_match", "unavailable", "locked"}
    assert PHRASES.handoff_offer in PHRASES.failure_replies["unavailable"]
    assert PHRASES.handoff_offer in PHRASES.failure_replies["locked"]
