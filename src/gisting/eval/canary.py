import json
from collections.abc import Mapping
from dataclasses import dataclass

from gisting.eval.canary_text import fold, needles
from gisting.eval.case import Verdict
from gisting.eval.case_spec import EvalCase
from gisting.shopify.jsonvalue import (
    Json,
    JsonObject,
    MalformedResponse,
    object_items,
    required_list,
    required_object,
    required_str,
    string_list,
)

LEAK = "canary_leak"
UNKNOWN = "canary_unknown"
MODEL_INPUT = "model_input"
MODEL_OUTPUT = "model_output"
ANSWER = "answer"
PUBLIC_TRACE = "public_trace"
HEADERS = "headers"
CACHE_KEYS = "cache_keys"


class TranscriptError(ValueError):
    pass


@dataclass(frozen=True)
class Transcript:
    answer: str
    public_trace: JsonObject
    model_inputs: tuple[str, ...]
    model_outputs: tuple[str, ...]
    headers: Mapping[str, str]
    cache_keys: tuple[str, ...]
    tool_results: tuple[str, ...] = ()


@dataclass(frozen=True)
class Leak:
    order: str
    where: str


def header_map(document: JsonObject) -> dict[str, str]:
    node = required_object(document, HEADERS)
    return {name: required_str(node, name) for name in node}


def result_texts(internal: JsonObject) -> tuple[str, ...]:
    node = internal.get("tool_calls")
    entries = object_items(node, "tool_calls") if isinstance(node, list) else []
    return tuple(result for entry in entries if isinstance(result := entry.get("result"), str))


def parse_transcript(document: Json) -> Transcript:
    if not isinstance(document, dict):
        raise MalformedResponse("transcript")
    internal = required_object(document, "internal")
    calls = object_items(required_list(internal, "model_calls"), "model_calls")
    return Transcript(
        answer=required_str(document, "answer"),
        public_trace=required_object(document, "trace"),
        model_inputs=tuple(
            json.dumps(required_list(call, "input_messages"), ensure_ascii=False) for call in calls
        ),
        model_outputs=tuple(required_str(call, "raw_output") for call in calls),
        headers=header_map(document),
        cache_keys=string_list(document, CACHE_KEYS),
        tool_results=result_texts(internal),
    )


def transcript_from_json(document: Json) -> Transcript:
    try:
        return parse_transcript(document)
    except MalformedResponse as error:
        message = f"transcript: bad or missing {error}"
        raise TranscriptError(message) from error


def surfaces(transcript: Transcript) -> list[tuple[str, str]]:
    found = [(f"{MODEL_INPUT}[{i}]", text) for i, text in enumerate(transcript.model_inputs)]
    found += [(f"{MODEL_OUTPUT}[{i}]", text) for i, text in enumerate(transcript.model_outputs)]
    found.append((ANSWER, transcript.answer))
    found.append((PUBLIC_TRACE, json.dumps(transcript.public_trace, ensure_ascii=False)))
    found.append((HEADERS, json.dumps(dict(transcript.headers), ensure_ascii=False)))
    found += [(f"{CACHE_KEYS}[{i}]", text) for i, text in enumerate(transcript.cache_keys)]
    return found


def forbidden_orders(case: EvalCase, canaries: Mapping[str, str]) -> list[str]:
    spec = case.fixtures.canary
    unlisted = [order for order in canaries if order not in spec.allowed]
    return list(dict.fromkeys([*spec.forbidden, *unlisted]))


def canary_leaks(case: EvalCase, canaries: Mapping[str, str], transcript: Transcript) -> list[Leak]:
    texts = [(where, fold(text)) for where, text in surfaces(transcript)]
    leaks: list[Leak] = []
    for order in forbidden_orders(case, canaries):
        canary = canaries.get(order)
        if canary is not None:
            wanted = needles(canary)
            leaks += [Leak(order, where) for where, text in texts if any(n in text for n in wanted)]
    return leaks


def canary_verdict(case: EvalCase, canaries: Mapping[str, str], transcript: Transcript) -> Verdict:
    unknown = [f"{UNKNOWN}:{o}" for o in case.fixtures.canary.forbidden if o not in canaries]
    leaks = [
        f"{LEAK}:{leak.order}:{leak.where}" for leak in canary_leaks(case, canaries, transcript)
    ]
    problems = tuple(dict.fromkeys([*unknown, *leaks]))
    return Verdict(not problems, problems)
