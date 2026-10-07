import unicodedata

import pytest
from eval_support import build_case, call_text, grader, verdict_of

from gisting.agent.search_guard import folded_terms
from gisting.eval.policy_call import latest_customer_text, words_of
from gisting.kb.bm25 import tokenize
from gisting.tools.search_policy import TOOL_NAME

SAMPLES = (
    "How long do I have to send something back?",
    "STANDARD Shipping costs $5.99 -- or 5,99?",
    "Ｒｅｔｕｒｎ １２３",
    "Straße café naïve ﬁrst Ⅸ ½",
    "İstanbul ẞ Σίσυφος",
    "order #1042, e-mail: ava.chen@example.com!",
    "① ² Ω Å ㎒ \U0001f600 smile",
    "",
)


def kb_words(text: str) -> tuple[str, ...]:
    once = unicodedata.normalize("NFKC", text)
    return tokenize(unicodedata.normalize("NFKC", once.casefold()))


@pytest.mark.parametrize("text", SAMPLES)
def test_the_grader_words_are_the_words_the_knowledge_base_and_the_agent_guard_use(
    text: str,
) -> None:
    assert words_of(text) == kb_words(text)
    assert words_of(text) == folded_terms(text)


def test_the_policy_arguments_and_tool_name_come_from_the_data() -> None:
    assert grader().policy.arguments == {"query"}
    assert grader().policy.tool == TOOL_NAME


def test_the_policy_categories_expect_the_search_decision() -> None:
    assert grader().first_turn["policy_question"] == "search"
    assert grader().first_turn["policy_outside_kb"] == "search"


def search(query: str, name: str = TOOL_NAME) -> str:
    return f'<tool_call>\n{{"name": "{name}", "arguments": {{"query": "{query}"}}}}\n</tool_call>'


def test_only_the_latest_customer_message_can_supply_the_query_words() -> None:
    spec = {
        "category": "policy_question",
        "messages": [
            {"role": "user", "content": "Do you ship to Canada?"},
            {"role": "assistant", "content": "Yes, we do."},
            {"role": "user", "content": "And what does that cost?"},
        ],
    }
    assert verdict_of(spec, search("cost")).ok
    verdict = verdict_of(spec, search("ship Canada cost"))
    assert not verdict.ok
    assert verdict.problems == ("query_term_not_said:canada,ship",)


def test_the_latest_customer_text_of_a_case_without_one_is_empty() -> None:
    spec = {"category": "policy_question", "messages": [{"role": "assistant", "content": "Hi"}]}
    assert latest_customer_text(build_case(spec)) == ""


@pytest.mark.parametrize("layer", ["raw", "final", "decision"])
def test_a_search_call_is_judged_the_same_at_every_layer(layer: str) -> None:
    spec = {"category": "policy_outside_kb", "user": "Do you offer gift wrapping?"}
    assert verdict_of(spec, search("gift wrapping"), layer).ok
    assert not verdict_of(spec, search("gift cards"), layer).ok


def test_a_lookup_call_for_a_policy_question_is_a_wrong_tool_and_has_wrong_arguments() -> None:
    spec = {"category": "policy_question", "user": "Do you ship to Canada?"}
    verdict = verdict_of(spec, call_text())
    assert {"wrong_tool_name", "unexpected_arguments"} <= set(verdict.problems)


def test_a_policy_question_with_an_order_number_is_not_a_search_decision() -> None:
    asking = {"category": "order_no_email", "user": "What is the return window for order #1042?"}
    assert not verdict_of(asking, search("return window")).ok
    calling = {
        "category": "order_full",
        "user": "Can I still return order #1042? My email is ava.chen@example.com.",
    }
    assert not verdict_of(calling, search("return order")).ok
