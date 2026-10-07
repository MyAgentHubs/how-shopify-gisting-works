import json
import re
from pathlib import Path

from gisting.eval.data_model import PolicyRules, QueryRules
from gisting.eval.text import canned_form
from gisting.prompt.phrases import ReplyPhrases
from gisting.shopify.jsonvalue import (
    Json,
    JsonObject,
    MalformedResponse,
    required_int,
    required_object,
    required_str,
    string_list,
)


def source_document(root: Path, sources: JsonObject, name: str) -> JsonObject:
    document: Json = json.loads(
        root.joinpath(required_str(sources, name)).read_text(encoding="utf-8")
    )
    if not isinstance(document, dict):
        raise MalformedResponse(name)
    return document


def load_query_rules(root: Path, sources: JsonObject) -> QueryRules:
    agent = source_document(root, sources, "agent_policy")
    limits = required_object(agent, "query_limits")
    order_range = required_object(source_document(root, sources, "lookup_policy"), "order_range")
    return QueryRules(
        max_chars=required_int(limits, "max_chars"),
        max_terms=required_int(limits, "max_terms"),
        stopwords=frozenset(
            string_list(source_document(root, sources, "search_params"), "stopwords")
        ),
        email=re.compile(required_str(required_object(agent, "patterns"), "email")),
        order_min=required_int(order_range, "min"),
        order_max=required_int(order_range, "max"),
    )


def load_policy_rules(document: JsonObject, phrases: ReplyPhrases, root: Path) -> PolicyRules:
    node = required_object(document, "policy")
    expectations = required_object(node, "expectations")
    sentence = required_str(node, "no_match_sentence")
    return PolicyRules(
        tool=required_str(node, "tool"),
        found_status=required_str(node, "found_status"),
        no_match_status=required_str(node, "no_match_status"),
        no_match_reply=canned_form(f"{sentence} {phrases.handoff_offer}"),
        expectations={name: string_list(expectations, name) for name in expectations},
        arguments=frozenset(string_list(node, "arguments")),
        query=load_query_rules(root, required_object(node, "sources")),
    )
