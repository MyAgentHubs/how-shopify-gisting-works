import re

import pytest
from agent_support import rules_replies

from gisting.agent.conclusions import find_conclusion, parse_conclusions
from gisting.agent.policy import Grounding, load_agent_policy
from gisting.eval.case import FIRST, Case
from gisting.eval.data import load_grader_data
from gisting.eval.grade import grade
from gisting.prompt.messages import UserMessage
from gisting.prompt.parse import parse_output
from gisting.prompt.rules import rules_text
from gisting.shopify.jsonvalue import MalformedResponse

POLICY = load_agent_policy()
CATEGORY = {"both": "order_no_number", "email": "order_no_email", "order_number": "order_no_number"}
WRITTEN = {
    "both": "Where is my order?",
    "email": "Where is order #1042?",
    "order_number": "Where is my order? ava.chen@example.com",
}


def test_the_rules_hold_neither_the_ask_sentences_nor_their_example_values() -> None:
    rules = rules_text()
    for reply in (*POLICY.needs_input_replies.values(), *POLICY.needs_input_bare_replies.values()):
        assert reply not in rules
    assert "for example" not in rules
    assert "name@example.com" not in rules


@pytest.mark.parametrize("key", ["both", "email", "order_number"])
def test_every_ask_template_passes_the_independent_grader_for_its_case(key: str) -> None:
    data = load_grader_data()
    case = Case(CATEGORY[key], FIRST, None, None, None, (UserMessage(WRITTEN[key]),))
    verdict = grade(case, parse_output(POLICY.needs_input_replies[key]), data)
    assert verdict.ok, verdict.problems


def test_the_email_template_does_not_ask_for_the_order_number_and_the_other_way_round() -> None:
    assert "email" not in POLICY.needs_input_replies["order_number"].lower()
    assert "order number" not in POLICY.needs_input_replies["email"].lower()


def test_the_rules_quote_a_fixed_reply_for_each_failure_status() -> None:
    assert set(rules_replies()) == {"no_match", "unavailable", "locked"}


@pytest.mark.parametrize("status", ["no_match", "unavailable", "locked"])
def test_every_fixed_failure_reply_in_the_rules_is_a_lookup_conclusion(status: str) -> None:
    found = find_conclusion(POLICY.conclusions, rules_replies()[status])
    assert found is not None
    assert found.reason == f"{status}_reply"


def test_the_decline_and_the_asks_in_the_rules_are_not_lookup_conclusions() -> None:
    sentences = re.findall(r'reply only "([^"]+)"', rules_text())
    assert len(sentences) == 1
    sentences += POLICY.needs_input_replies.values()
    assert all(find_conclusion(POLICY.conclusions, text) is None for text in sentences)


@pytest.mark.parametrize(
    "text",
    [
        "It's IN TRANSIT.",
        "Your parcel was Delivered.",
        "I couldn’t find an order matching that.",
        "Tracking: AB-123456",
        "Tracking 1Z999AA10123456784",
        "Tracking 4000012345678",
        "via UPS",
    ],
)
def test_conclusions_are_found_case_insensitively_with_curly_apostrophes(text: str) -> None:
    assert find_conclusion(POLICY.conclusions, text) is not None


@pytest.mark.parametrize(
    "text",
    [
        "Please wait while I check.",
        "Sorry, I can only help with order and delivery questions.",
        "Your cups arrived? Tell me more.",
        "Order #1042 please.",
        "Undeliverable addresses cannot be handled here.",
    ],
)
def test_ordinary_sentences_are_not_conclusions(text: str) -> None:
    assert find_conclusion(POLICY.conclusions, text) is None


def test_the_ask_templates_cover_exactly_the_guarded_inputs() -> None:
    assert set(POLICY.needs_input_replies) == {"both", Grounding.EMAIL, Grounding.ORDER_NUMBER}


@pytest.mark.parametrize(
    "text",
    ["[]", "{}", '{"status_word": []}', '{"status_word": "x"}', '{"status_word": ["("]}'],
)
def test_a_malformed_conclusion_list_is_rejected(text: str) -> None:
    with pytest.raises((MalformedResponse, ValueError)):
        parse_conclusions(text)
