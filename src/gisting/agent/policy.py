import json
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from gisting.agent.answers import AnswerRules, parse_answer_rules
from gisting.agent.conclusions import Conclusions, load_conclusions
from gisting.agent.consent import (
    AskDetection,
    ConsentGuard,
    Patterns,
    compiled,
    parse_ask_detection,
    parse_consent_guard,
)
from gisting.agent.rules_echo import RulesEcho, parse_rules_echo
from gisting.agent.time_claims import TimeRules, load_time_rules
from gisting.kb.params import Bm25Params, load_params
from gisting.prompt.files import PROMPTS_DIR
from gisting.prompt.phrases import ReplyPhrases, load_phrases
from gisting.shopify.jsonvalue import (
    Json,
    JsonObject,
    MalformedResponse,
    required_int,
    required_object,
    required_str,
    string_list,
)
from gisting.tools.search_policy import PARAMS_FILE as SEARCH_PARAMS_FILE

POLICY_FILE = PROMPTS_DIR / "agent_policy.json"
ASK_DETECTION_FILE = PROMPTS_DIR / "ask_detection.json"


class AgentPolicyError(ValueError):
    pass


INVALID_STATUS = "invalid_tool_call"
BOTH_MISSING = "both"


class Grounding(StrEnum):
    EMAIL = "email"
    ORDER_NUMBER = "order_number"
    QUERY_TERMS = "query_terms"


PATTERNED = (Grounding.EMAIL, Grounding.ORDER_NUMBER)


class InvalidCode(StrEnum):
    MALFORMED_CALL = "malformed_call"
    UNKNOWN_TOOL = "unknown_tool"
    INVALID_ARGUMENTS = "invalid_arguments"
    UNGUARDED_TOOL = "unguarded_tool"
    ONE_LOOKUP_AT_A_TIME = "one_lookup_at_a_time"
    ONE_SEARCH_AT_A_TIME = "one_search_at_a_time"
    QUERY_REFUSED = "query_refused"


class FallbackReason(StrEnum):
    INVALID_TOOL_CALL = "invalid_tool_call"
    TOOL_CALL_LIMIT = "tool_call_limit"
    EMPTY_ANSWER = "empty_answer"
    UNCHECKED_CONCLUSION = "unchecked_conclusion"
    UNRENDERABLE_ORDER = "unrenderable_order"
    POLICY_UNAVAILABLE = "policy_unavailable"


@dataclass(frozen=True)
class QueryLimits:
    max_chars: int
    max_terms: int


@dataclass(frozen=True)
class AgentPolicy:
    max_tool_calls: int
    max_invalid_calls: int
    max_new_tokens: int
    rules_echo: RulesEcho
    fallback_replies: dict[FallbackReason, str]
    grounded_arguments: dict[str, dict[str, Grounding]]
    patterns: dict[Grounding, re.Pattern[str]]
    needs_input_result: JsonObject
    needs_input_replies: dict[str, str]
    needs_input_bare_replies: dict[str, str]
    conclusions: Conclusions
    time_rules: TimeRules
    ask_detection: AskDetection
    consent_guards: dict[str, ConsentGuard]
    order_hints: Patterns
    forged_structures: dict[str, re.Pattern[str]]
    override_requests: dict[str, re.Pattern[str]]
    override_unconditional: frozenset[str]
    consent_exempt: frozenset[str]
    needs_consent_result: JsonObject
    needs_consent_replies: dict[str, str]
    answers: AnswerRules
    dropped_placeholder: str
    withheld_placeholder: str
    query_limits: QueryLimits
    search_params: Bm25Params


def mixes_query_terms(rules: dict[str, Grounding]) -> bool:
    kinds = set(rules.values())
    return Grounding.QUERY_TERMS in kinds and kinds != {Grounding.QUERY_TERMS}


def parse_grounded(node: JsonObject) -> dict[str, dict[str, Grounding]]:
    grounded = {
        tool: {arg: Grounding(required_str(rules, arg)) for arg in rules}
        for tool, rules in ((tool, required_object(node, tool)) for tool in node)
    }
    if any(mixes_query_terms(rules) for rules in grounded.values()):
        raise MalformedResponse("grounded_arguments")
    return grounded


def parse_consent_guards(
    node: JsonObject, phrases: ReplyPhrases, words: JsonObject
) -> dict[str, ConsentGuard]:
    return {tool: parse_consent_guard(required_object(node, tool), phrases, words) for tool in node}


def parse_patterns(node: JsonObject) -> dict[Grounding, re.Pattern[str]]:
    if set(node) != {kind.value for kind in PATTERNED}:
        raise MalformedResponse("patterns")
    try:
        compiled = {kind: re.compile(required_str(node, kind.value)) for kind in PATTERNED}
    except re.error as error:
        raise MalformedResponse("patterns") from error
    if compiled[Grounding.ORDER_NUMBER].groups != 1:
        raise MalformedResponse("patterns")
    return compiled


def parse_named_patterns(node: JsonObject, key: str) -> dict[str, re.Pattern[str]]:
    found = required_object(node, key)
    try:
        return {name: re.compile(required_str(found, name), re.IGNORECASE) for name in found}
    except re.error as error:
        raise MalformedResponse(key) from error


def parse_query_limits(node: JsonObject) -> QueryLimits:
    limits = QueryLimits(required_int(node, "max_chars"), required_int(node, "max_terms"))
    if min(limits.max_chars, limits.max_terms) < 1:
        raise MalformedResponse("query_limits")
    return limits


def fallback_reply(replies: JsonObject, reason: FallbackReason, phrases: ReplyPhrases) -> str:
    node = replies[reason.value]
    if not isinstance(node, dict):
        return required_str(replies, reason.value)
    named = (
        phrases.sentences.get(required_str(node, "sentence"))
        if "sentence" in node
        else phrases.failure_replies.get(required_str(node, "failure_reply"))
    )
    if named is None:
        raise MalformedResponse("fallback_replies")
    return named


@dataclass(frozen=True)
class PolicyParts:
    conclusions: Conclusions
    time_rules: TimeRules
    phrases: ReplyPhrases
    detection: AskDetection
    search_params: Bm25Params


def parse_policy(text: str, parts: PolicyParts) -> AgentPolicy:
    phrases = parts.phrases
    document: Json = json.loads(text)
    if not isinstance(document, dict):
        raise MalformedResponse("policy")
    replies = required_object(document, "fallback_replies")
    if set(replies) != {reason.value for reason in FallbackReason}:
        raise MalformedResponse("fallback_replies")
    guards = parse_consent_guards(
        required_object(document, "consent_guards"),
        phrases,
        required_object(document, "consent_words"),
    )
    policy = AgentPolicy(
        max_tool_calls=required_int(document, "max_tool_calls_per_turn"),
        max_invalid_calls=required_int(document, "max_invalid_tool_calls_per_turn"),
        max_new_tokens=required_int(document, "max_new_tokens"),
        rules_echo=parse_rules_echo(required_object(document, "rules_echo"), phrases),
        fallback_replies={r: fallback_reply(replies, r, phrases) for r in FallbackReason},
        grounded_arguments=parse_grounded(required_object(document, "grounded_arguments")),
        patterns=parse_patterns(required_object(document, "patterns")),
        needs_input_result=required_object(document, "needs_input_result"),
        needs_input_replies=dict(phrases.ask),
        needs_input_bare_replies=dict(phrases.ask_bare),
        conclusions=parts.conclusions,
        time_rules=parts.time_rules,
        ask_detection=parts.detection,
        consent_guards=guards,
        order_hints=compiled(document, "order_hints"),
        forged_structures=parse_named_patterns(document, "forged_structures"),
        override_requests=parse_named_patterns(document, "override_requests"),
        override_unconditional=frozenset(string_list(document, "override_unconditional")),
        consent_exempt=frozenset(string_list(document, "consent_exempt")),
        needs_consent_result=required_object(document, "needs_consent_result"),
        needs_consent_replies={tool: guard.offer_text for tool, guard in guards.items()},
        answers=parse_answer_rules(required_object(document, "answers"), phrases),
        dropped_placeholder=required_str(required_object(document, "context_drop"), "placeholder"),
        withheld_placeholder=required_str(document, "withheld_placeholder"),
        query_limits=parse_query_limits(required_object(document, "query_limits")),
        search_params=parts.search_params,
    )
    if not isinstance(policy.needs_input_result.get("missing"), list):
        raise MalformedResponse("needs_input_result")
    if not isinstance(policy.needs_consent_result.get("missing"), list):
        raise MalformedResponse("needs_consent_result")
    if min(policy.max_tool_calls, policy.max_new_tokens) < 1 or policy.max_invalid_calls < 0:
        raise MalformedResponse("limits")
    if not policy.override_unconditional <= policy.override_requests.keys():
        raise MalformedResponse("override_unconditional")
    return policy


def load_agent_policy(
    path: Path = POLICY_FILE, search_params: Path = SEARCH_PARAMS_FILE
) -> AgentPolicy:
    try:
        detection = parse_ask_detection(json.loads(ASK_DETECTION_FILE.read_text(encoding="utf-8")))
        parts = PolicyParts(
            load_conclusions(),
            load_time_rules(),
            load_phrases(),
            detection,
            load_params(search_params),
        )
        return parse_policy(path.read_text(encoding="utf-8"), parts)
    except (OSError, ValueError) as error:
        message = f"{type(error).__name__}: {error}"
        raise AgentPolicyError(message) from error
