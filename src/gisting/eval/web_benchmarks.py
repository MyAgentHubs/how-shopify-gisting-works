from collections.abc import Sequence
from dataclasses import dataclass
from typing import get_args

from gisting.eval.baseline import Mode
from gisting.shopify.jsonvalue import (
    Json,
    JsonObject,
    MalformedResponse,
    object_items,
    required_int,
    required_list,
    required_object,
    required_str,
    string_list,
)

REDLINE_GATE = "redline"
MODES: tuple[Mode, ...] = get_args(Mode)


@dataclass(frozen=True)
class BenchmarkSource:
    code_tree_sha: str
    rules_version: str
    backend_id: str
    splits: tuple[str, ...]
    graded: int


@dataclass(frozen=True)
class TokenUse:
    turns: int
    model_calls: int
    rules_tokens_per_call: float
    prefill_tokens_per_turn: float
    total_tokens_per_turn: float


@dataclass(frozen=True)
class Tokens:
    full: TokenUse
    gist: TokenUse


@dataclass(frozen=True)
class Rate:
    failures: int
    n: int
    rate: float
    upper95: float


@dataclass(frozen=True)
class Layers:
    raw: Rate
    final: Rate


@dataclass(frozen=True)
class RedLineMode:
    full: Layers
    gist: Layers


@dataclass(frozen=True)
class RedLine:
    metric: str
    min_cases: int
    results: RedLineMode


@dataclass(frozen=True)
class Composition:
    tools_tokens_per_call: int
    chat_tokens_per_call: int
    calls_per_case: float
    saved_per_call: int
    saved_per_turn: float
    prefix_tokens: int
    full_call_tokens: int
    gist_call_tokens: int


@dataclass(frozen=True)
class Benchmarks:
    source: BenchmarkSource
    tokens: Tokens
    composition: Composition
    red_lines: tuple[RedLine, ...]


def required_number(parent: JsonObject, key: str) -> float:
    value = parent.get(key)
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise MalformedResponse(key)
    return float(value)


def rate_of(parent: JsonObject) -> Rate:
    return Rate(
        required_int(parent, "failures"),
        required_int(parent, "n"),
        required_number(parent, "rate"),
        required_number(parent, "upper95"),
    )


def layers_of(metric: JsonObject) -> Layers:
    layers = required_object(metric, "layers")
    return Layers(
        rate_of(required_object(layers, "raw")), rate_of(required_object(layers, "final"))
    )


def token_use_of(report: JsonObject) -> TokenUse:
    tokens = required_object(report, "tokens")
    return TokenUse(
        required_int(tokens, "turns"),
        required_int(tokens, "model_calls"),
        required_number(tokens, "rules_tokens_per_call"),
        required_number(tokens, "prefill_tokens_per_turn"),
        required_number(tokens, "total_tokens_per_turn"),
    )


def source_of(report: JsonObject) -> BenchmarkSource:
    run = required_object(report, "run")
    cases = required_object(report, "cases")
    return BenchmarkSource(
        required_str(run, "code_tree_sha"),
        required_str(run, "rules_version"),
        required_str(run, "backend_id"),
        string_list(cases, "splits"),
        required_int(cases, "graded"),
    )


def red_line_names(report: JsonObject) -> list[str]:
    metrics = required_object(report, "metrics")
    return [
        name
        for name, metric in metrics.items()
        if isinstance(metric, dict) and metric.get("gate") == REDLINE_GATE
    ]


def red_line_of(name: str, full: JsonObject, gist: JsonObject) -> RedLine:
    full_metric = required_object(required_object(full, "metrics"), name)
    gist_metric = required_object(required_object(gist, "metrics"), name)
    return RedLine(
        name,
        required_int(full_metric, "min_cases"),
        RedLineMode(layers_of(full_metric), layers_of(gist_metric)),
    )


def check_pair(full: JsonObject, gist: JsonObject) -> None:
    modes: list[Json] = [
        required_object(full, "run").get("mode"),
        required_object(gist, "run").get("mode"),
    ]
    if modes != list(MODES) or source_of(full) != source_of(gist):
        message = "reports are not a full and gist pair of one run"
        raise MalformedResponse(message)


def call_token_rows(rows: Sequence[JsonObject]) -> list[JsonObject]:
    calls: list[JsonObject] = []
    for row in rows:
        internal = required_object(row, "internal")
        for call in object_items(required_list(internal, "model_calls"), "model_calls"):
            calls.append(required_object(call, "tokens"))
    return calls


def composition_of(
    source: BenchmarkSource, tokens: Tokens, rows: Sequence[JsonObject]
) -> Composition:
    calls = call_token_rows(rows)
    tool_sizes = {required_int(call, "tools") for call in calls}
    rule_sizes = {float(required_int(call, "rules")) for call in calls}
    counted = len(rows) == source.graded and len(calls) == tokens.gist.model_calls
    if not counted or len(tool_sizes) != 1 or rule_sizes != {tokens.gist.rules_tokens_per_call}:
        message = "transcripts do not match the gist report"
        raise MalformedResponse(message)
    (tools,) = tool_sizes
    chat_total = sum(
        required_int(call, "history") + required_int(call, "tool_results") for call in calls
    )
    chat = round(chat_total / len(calls))
    full_rules = round(tokens.full.rules_tokens_per_call)
    gist_rules = round(tokens.gist.rules_tokens_per_call)
    calls_per_case = len(calls) / source.graded
    return Composition(
        tools,
        chat,
        calls_per_case,
        full_rules - gist_rules,
        (full_rules - gist_rules) * calls_per_case,
        full_rules + tools,
        full_rules + tools + chat,
        gist_rules + tools + chat,
    )


def build_benchmarks(
    full: JsonObject, gist: JsonObject, gist_transcripts: Sequence[JsonObject]
) -> Benchmarks:
    check_pair(full, gist)
    names = red_line_names(full)
    if names != red_line_names(gist):
        message = "reports gate different red lines"
        raise MalformedResponse(message)
    source = source_of(full)
    tokens = Tokens(token_use_of(full), token_use_of(gist))
    return Benchmarks(
        source,
        tokens,
        composition_of(source, tokens, gist_transcripts),
        tuple(red_line_of(name, full, gist) for name in names),
    )
