from collections.abc import Sequence
from dataclasses import replace
from enum import StrEnum
from typing import cast

from gisting.agent.consent import latest_exchange
from gisting.agent.context import written_orders
from gisting.agent.policy import AgentPolicy, Grounding
from gisting.agent.state import AgentDeps
from gisting.agent.text_view import plain
from gisting.kb.bm25 import tokenize
from gisting.kb.params import Bm25Params
from gisting.prompt.messages import Message
from gisting.prompt.parse import CallRequest
from gisting.shopify.jsonvalue import JsonObject


class QueryRefusal(StrEnum):
    ORDER_IN_MESSAGE = "order_number_in_message"
    TOO_LONG = "query_too_long"
    TOO_MANY_TERMS = "query_too_many_terms"
    QUERY_HAS_EMAIL = "query_has_email"
    QUERY_HAS_ORDER = "query_has_order_number"
    EMPTY = "empty_query"
    ONLY_FILLER = "query_only_filler_words"
    TERM_NOT_SAID = "query_term_not_in_latest_message"


def folded_terms(text: str) -> tuple[str, ...]:
    return tokenize(plain(plain(text).casefold()))


def search_terms(params: Bm25Params, text: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(term for term in folded_terms(text) if term not in params.stopwords))


def normalized_query(params: Bm25Params, query: str) -> str:
    return " ".join(search_terms(params, query))


def query_arguments(policy: AgentPolicy, name: str) -> list[str]:
    rules = policy.grounded_arguments.get(name, {})
    return [arg for arg, kind in rules.items() if kind is Grounding.QUERY_TERMS]


def normalized_call(policy: AgentPolicy, call: CallRequest) -> CallRequest:
    given = cast(JsonObject, call.arguments)
    fixed = {
        arg: normalized_query(policy.search_params, str(given.get(arg)))
        for arg in query_arguments(policy, call.name or "")
    }
    return replace(call, arguments={**given, **fixed}) if fixed else call


def shape_refusal(policy: AgentPolicy, query: str) -> QueryRefusal | None:
    limits = policy.query_limits
    if len(query) > limits.max_chars:
        return QueryRefusal.TOO_LONG
    if len(search_terms(policy.search_params, query)) > limits.max_terms:
        return QueryRefusal.TOO_MANY_TERMS
    return None


def content_refusal(deps: AgentDeps, query: str) -> QueryRefusal | None:
    email = deps.policy.patterns[Grounding.EMAIL]
    if any(email.search(view) for view in (query, plain(query))):
        return QueryRefusal.QUERY_HAS_EMAIL
    if written_orders(deps.policy, deps.lookup, query):
        return QueryRefusal.QUERY_HAS_ORDER
    return None


def terms_refusal(policy: AgentPolicy, query: str, said: str) -> QueryRefusal | None:
    if not folded_terms(query):
        return QueryRefusal.EMPTY
    wanted = search_terms(policy.search_params, query)
    if not wanted:
        return QueryRefusal.ONLY_FILLER
    return None if set(wanted) <= set(folded_terms(said)) else QueryRefusal.TERM_NOT_SAID


def query_refusal(deps: AgentDeps, query: str, said: str) -> QueryRefusal | None:
    return (
        shape_refusal(deps.policy, query)
        or content_refusal(deps, query)
        or terms_refusal(deps.policy, query, said)
    )


def search_refusal(
    deps: AgentDeps, messages: Sequence[Message], name: str, arguments: JsonObject
) -> QueryRefusal | None:
    queries = query_arguments(deps.policy, name)
    if not queries:
        return None
    said = latest_exchange(messages)[0]
    if written_orders(deps.policy, deps.lookup, said):
        return QueryRefusal.ORDER_IN_MESSAGE
    for arg in queries:
        value = arguments.get(arg)
        found = query_refusal(deps, value if isinstance(value, str) else "", said)
        if found is not None:
            return found
    return None
