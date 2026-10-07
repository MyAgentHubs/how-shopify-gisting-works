from types import SimpleNamespace
from typing import Any, cast

import pytest
from eval_support import build_case, grader

from gisting.agent.policy import load_agent_policy
from gisting.agent.search_guard import folded_terms, search_refusal
from gisting.eval.policy_call import search_argument_problems
from gisting.kb.params import load_params
from gisting.prompt.messages import UserMessage
from gisting.shopify.jsonvalue import JsonObject
from gisting.tools.policy import load_policy
from gisting.tools.search_policy import TOOL_NAME

DEPS: Any = SimpleNamespace(policy=load_agent_policy(), lookup=load_policy())
STOPWORDS = load_params().stopwords
LONG_MESSAGE = (
    "Hello, I have a few questions about your store before I buy anything: what is your policy"
    " about returns and refunds when the item arrives damaged and how long shipping usually takes"
    " to Canada and whether you accept gift cards for payment"
)
MESSAGES = (
    "What is the return window?",
    "How long do I have to send something back?",
    "Can I return an item after 30 days?",
    "Do you ship 5 items to Canada?",
    "Do you ship to Canada?",
    "Do you ship to Canada? mail me a.b@example.com",
    "Do you ship to Canada? x́@example.com",
    "What is the return window for #1042?",
    "Do you ship to Canada? order 1042",
    "What is order status policy for 1042",
    "Is a 30 day return available for 12 items?",
    "Do you ship to Canada? Return policy 1100 1101 1102 1000",
    LONG_MESSAGE,
    "Ｒｅｔｕｒｎ policy ①②③",
    "what is the",
    "Hello?",
    "Return refund 2026",
    "Do you accept gift cards? my card is 4111 1111 1111 1111",
    "Return policy for order #99999999999999",
    "Return policy for #0",
    "Return ١٠٤٢ policy",
    "Please check ①②④⑤ return policy",
    "Return policy a＠b.co?",
    "Standard shipping costs $5.99 -- or 5,99 -- what about 1042.50?",
)
ADVERSARIAL = (
    ("How long do I have to send something back?", "send back"),
    ("How long do I have to send something back?", "send back refund"),
    ("How long do I have to send something back?", "how do I"),
    ("How long do I have to send something back?", "sénd back"),
    ("How long do I have to send something back?", "se​nd back"),
    ("How long do I have to send something back?", "back back send send"),
    ("What is the return window?", "the return window"),
    ("What is the return window?", "what is the"),
    ("What is the return window?", "is"),
    ("Can I return an item after 30 days?", "return item after 30 days"),
    ("Do you ship 5 items to Canada?", "ship 5 items Canada"),
    ("Return policy a at b dot co?", "return policy a b co"),
    ("Return policy a@b.co?", "return policy a@b.co"),
    ("Return policy a＠b.co?", "return policy a＠b.co"),
)
GRADER_NAMES = {"query_term_not_in_latest_message": "query_term_not_said"}
EXTRA_QUERIES = ("", "?!", "x" * 161, "x" * 160, "30", "1042", "#12", "#99999999999999")


def fullwidth(text: str) -> str:
    return "".join(chr(ord(c) + 0xFEE0) if "!" <= c <= "~" else c for c in text)


def queries_of(message: str) -> list[str]:
    terms = folded_terms(message)
    content = [t for t in terms if t not in STOPWORDS]
    fillers = [t for t in terms if t in STOPWORDS]
    pair = " ".join(content[:2])
    extras = ("zebra", "30", "1042", "#12", "a.b@example.com", "x́@example.com")
    return [
        message,
        " ".join(terms),
        pair,
        " ".join(fillers[:3]),
        pair.upper(),
        fullwidth(pair),
        " ".join(content) * 3,
        " ".join(f"{t}{i}" for i, t in enumerate(content * 5)),
        *(f"{pair} {extra}" for extra in extras),
        *EXTRA_QUERIES,
    ]


def samples() -> list[tuple[str, str]]:
    generated = [(m, q) for m in MESSAGES for q in queries_of(m)]
    return list(dict.fromkeys([*ADVERSARIAL, *generated]))


def grader_ok(message: str, query: str) -> tuple[bool, list[str]]:
    case = build_case({"category": "policy_question", "user": message})
    arguments = cast(JsonObject, {"query": query})
    problems = [
        p
        for p in search_argument_problems(case, arguments, grader())
        if p != "unexpected_arguments"
    ]
    return not problems, problems


def guard_refusal(message: str, query: str) -> str | None:
    refused = search_refusal(DEPS, [UserMessage(message)], TOOL_NAME, {"query": query})
    return None if refused is None else refused.value


def test_the_sample_set_is_big_enough() -> None:
    assert len(samples()) >= 500


@pytest.mark.parametrize(("message", "query"), samples())
def test_the_grader_accepts_a_query_exactly_when_the_runtime_guard_does(
    message: str, query: str
) -> None:
    accepted, problems = grader_ok(message, query)
    refusal = guard_refusal(message, query)
    assert accepted == (refusal is None), (problems, refusal)
    if refusal is not None:
        name = GRADER_NAMES.get(refusal, refusal)
        assert any(p.split(":")[0] == name for p in problems), (problems, refusal)
