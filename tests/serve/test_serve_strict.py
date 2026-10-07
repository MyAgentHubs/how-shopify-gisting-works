import copy
import json
from dataclasses import asdict
from typing import Any

import pytest
from serve_http import GOOD_SESSION, started
from serve_support import INTERNAL_CANARY, PUBLIC_TRACE, FakeTurn, make_service

from gisting.agent.public_trace import PublicTrace
from gisting.agent.trace import Traces
from gisting.eval.dataclass_json import decode_as
from gisting.serve.contract import GenerateRequest
from gisting.serve.service import Refused, Served
from gisting.serve.strict import TraceRejected, round_trip

FULL: dict[str, Any] = {
    "tools": [{"tool": "lookup_order", "order_number": "#1042", "outcome": "completed"}],
    "knowledge": [{"id": "kb-shipping-times", "method": "bm25"}],
    "tokens": {"rules": 100, "tools": 90, "history": 80, "tool_results": 0, "total": 270},
    "latency": {"first_token_ms": 12.5, "total_ms": 40},
}


def mutated(path: list[str | int], value: object) -> dict[str, Any]:
    document = copy.deepcopy(FULL)
    node: Any = document
    for step in path[:-1]:
        node = node[step]
    node[path[-1]] = value
    return document


def test_a_good_document_round_trips_like_the_contract_decoder() -> None:
    expected = json.loads(json.dumps(asdict(decode_as(PublicTrace, FULL))))
    assert round_trip(PublicTrace, FULL) == expected
    assert round_trip(PublicTrace, PUBLIC_TRACE) == json.loads(
        json.dumps(asdict(decode_as(PublicTrace, PUBLIC_TRACE)))
    )


@pytest.mark.parametrize(
    "path",
    [["tools", 0, "secret"], ["knowledge", 0, "score"], ["tokens", "extra"], ["latency", "extra"]],
)
def test_extra_nested_fields_are_dropped_not_passed_on(path: list[str | int]) -> None:
    document = mutated(path, INTERNAL_CANARY)
    result = round_trip(PublicTrace, document)
    assert INTERNAL_CANARY not in json.dumps(result)
    assert result == round_trip(PublicTrace, FULL)


@pytest.mark.parametrize(
    "document",
    [
        mutated(["tokens", "total"], True),
        mutated(["tokens", "total"], "270"),
        mutated(["tokens", "total"], 1.5),
        mutated(["tools", 0, "outcome"], "deleted"),
        mutated(["tools", 0, "order_number"], 1042),
        mutated(["tools"], {"tool": "x"}),
        mutated(["knowledge", 0, "id"], "Not A Valid Id"),
        mutated(["knowledge", 0, "id"], "kb-" + "a" * 70),
        mutated(["knowledge", 0, "method"], "vector"),
        mutated(["knowledge"], [FULL["knowledge"][0]] * 4),
        mutated(["latency", "total_ms"], "40"),
        mutated(["latency"], None),
        {key: value for key, value in FULL.items() if key != "latency"},
        {**FULL, "tokens": {"rules": 1}},
    ],
)
def test_a_wrongly_shaped_document_is_rejected(document: dict[str, Any]) -> None:
    with pytest.raises(TraceRejected):
        round_trip(PublicTrace, document)


def test_a_knowledge_id_with_a_trailing_newline_is_rejected() -> None:
    with pytest.raises(TraceRejected):
        round_trip(PublicTrace, mutated(["knowledge", 0, "id"], "kb-shipping\n"))


def test_integers_become_floats_for_float_fields() -> None:
    assert round_trip(PublicTrace, FULL)["latency"] == {"first_token_ms": 12.5, "total_ms": 40.0}


def serve_with(document: dict[str, Any]) -> Served | Refused:
    turn = FakeTurn()
    turn.result_traces = Traces(document, {"reply_source": "model"})
    return make_service(turn).handle(GenerateRequest(GOOD_SESSION, "hi", "gist")).result


def test_the_service_serves_only_the_modelled_fields() -> None:
    served = serve_with(mutated(["tools", 0, "secret"], INTERNAL_CANARY))
    assert isinstance(served, Served)
    assert INTERNAL_CANARY not in json.dumps(served.trace)
    assert served.tokens == 270


def test_the_service_fails_closed_on_a_wrongly_typed_trace() -> None:
    assert serve_with(mutated(["tokens", "total"], "270")) == Refused(
        "internal", detail="TraceRejected"
    )


def test_a_nested_canary_never_reaches_the_http_response() -> None:
    turn = FakeTurn()
    turn.result_traces = Traces(mutated(["knowledge", 0, "score"], INTERNAL_CANARY), {})
    with started(turn) as app:
        body = {"session_id": GOOD_SESSION, "message": "hi", "mode": "gist"}
        reply = app.generate(body)
    assert reply.status == 200
    assert INTERNAL_CANARY.encode() not in reply.body
