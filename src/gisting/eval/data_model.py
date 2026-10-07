import re
from dataclasses import dataclass

Pattern = re.Pattern[str]


@dataclass(frozen=True)
class Limits:
    reply_max_chars: int
    call_content_max_chars: int
    leak_words: int
    echo_words: int
    forged_value_min_chars: int
    order_digits_max: int


@dataclass(frozen=True)
class Opener:
    opening: Pattern
    closing: Pattern | None


@dataclass(frozen=True)
class Forged:
    openers: tuple[Opener, ...]
    value: Pattern
    json_start: Pattern
    json_search_chars: int


@dataclass(frozen=True)
class Negation:
    clause_break: Pattern
    negator: Pattern


@dataclass(frozen=True)
class Weekday:
    name: str
    pattern: Pattern


@dataclass(frozen=True)
class NumberWord:
    word: str
    value: int
    pattern: Pattern


@dataclass(frozen=True)
class Vocabulary:
    weekdays: tuple[Weekday, ...]
    months: dict[str, int]
    month_only: tuple[tuple[int, Pattern], ...]
    day_words: dict[str, int]
    number_words: tuple[NumberWord, ...]
    date_patterns: tuple[Pattern, ...]
    time_patterns: tuple[Pattern, ...]
    number: Pattern
    relative: tuple[Pattern, ...]
    carriers: tuple[Pattern, ...]
    carrier_prefix: Pattern
    neutral_entities: frozenset[str]
    tracking_token: Pattern
    tracking_label: Pattern


@dataclass(frozen=True)
class Scenario:
    required_any: tuple[Pattern, ...]
    forbidden: tuple[Pattern, ...]
    forbidden_always: tuple[Pattern, ...]
    status_words: tuple[Pattern, ...]


@dataclass(frozen=True)
class Markers:
    leak: tuple[Pattern, ...]
    instruction: tuple[Pattern, ...]
    compliance: tuple[Pattern, ...]


@dataclass(frozen=True)
class Inputs:
    email_token: Pattern
    order_token: Pattern


@dataclass(frozen=True)
class Style:
    max_sentences: int
    max_sentences_by_line: dict[str, int]
    several_parcels_from: int
    several_parcels_from_by_line: dict[str, int]
    max_parcels: int
    max_words_per_sentence: int
    sentence_break: Pattern
    markdown: tuple[Pattern, ...]
    enum_name: Pattern
    enum_value: Pattern
    readable_date_forbidden: tuple[Pattern, ...]


@dataclass(frozen=True)
class FoundRules:
    status_anywhere_lines: frozenset[str]
    handoff_lines: frozenset[str]
    handoff_untracked_lines: frozenset[str]
    reassurance_lines: frozenset[str]
    reminder_lines: frozenset[str]
    no_thanks_lines: frozenset[str]
    partial_status: str
    forbidden_words: tuple[Pattern, ...]
    empathy: frozenset[str]
    reassurance: str
    reminder_offer: str
    thanks: str
    unshipped_rest: tuple[Pattern, ...]
    invented_reason: tuple[Pattern, ...]
    handoff: tuple[Pattern, ...]
    contact_carrier: tuple[Pattern, ...]
    no_estimate_words: tuple[Pattern, ...]
    estimate_markers: tuple[Pattern, ...]
    marker_window_words: int
    no_tracking: tuple[Pattern, ...]
    no_date: tuple[Pattern, ...]
    unfilled_slot: Pattern
    single_parcel_lines: frozenset[str]
    parcel_scenarios: dict[str, str]
    many_parcels_reply: str
    fulfillment_words: dict[str, str]
    status_alternatives: dict[str, tuple[str, ...]]
    transport_words: dict[str, str]
    parcel_words: dict[str, str]
    delivered_status: str
    closing_when: dict[str, frozenset[str]]


@dataclass(frozen=True)
class ToolRules:
    handoff_tool: str
    reminder_tool: str
    handoff_arguments: frozenset[str]
    reminder_arguments: frozenset[str]
    done_claims: tuple[Pattern, ...]
    confirmations: dict[str, str]


@dataclass(frozen=True)
class QueryRules:
    max_chars: int
    max_terms: int
    stopwords: frozenset[str]
    email: Pattern
    order_min: int
    order_max: int


@dataclass(frozen=True)
class PolicyRules:
    tool: str
    found_status: str
    no_match_status: str
    no_match_reply: str
    expectations: dict[str, tuple[str, ...]]
    arguments: frozenset[str]
    query: QueryRules


@dataclass(frozen=True)
class GraderData:
    expected_tool: str
    tools: ToolRules
    tool_arguments: frozenset[str]
    first_turn: dict[str, str]
    limits: Limits
    decline_replies: tuple[str, ...]
    canned: tuple[Pattern, ...]
    refusal: dict[str, tuple[Pattern, ...]]
    refusal_accepts: dict[str, tuple[str, ...]]
    ask_items: dict[str, tuple[Pattern, ...]]
    ask_requests: tuple[Pattern, ...]
    ask_keys: dict[str, str]
    ask_sentences: dict[str, str]
    ask_bare_sentences: frozenset[str]
    example_spans: tuple[Pattern, ...]
    inputs: Inputs
    style: Style
    found: FoundRules
    markers: Markers
    forged: Forged
    negation: Negation
    promises: tuple[Pattern, ...]
    exposure: tuple[Pattern, ...]
    vocabulary: Vocabulary
    scenarios: dict[str, Scenario]
    fact_claims: tuple[Pattern, ...]
    failure_scenarios: frozenset[str]
    handoff_scenarios: frozenset[str]
    policy_statuses: frozenset[str]
    policy: PolicyRules
    parcel_labels: Pattern
    rules_texts: tuple[str, ...]
