import json
from pathlib import Path
from typing import cast

import pytest

from gisting.agent.public_trace import PublicTrace
from gisting.eval.dataclass_json import DecodeError, decode_as, json_schema
from gisting.serve.config import LIMITS, ConfigError, load_limits
from gisting.serve.contract import (
    ERROR_TYPES,
    ErrorInfo,
    ErrorResponse,
    GenerateRequest,
    GenerateResponse,
    HealthReport,
    RequestRejected,
    ServeContract,
    decode_request,
)

ROOT = Path(__file__).resolve().parents[2]
GOOD = {"session_id": "abcdefgh", "message": "where is my order", "mode": "gist"}


def rejected(document: object) -> str:
    with pytest.raises(RequestRejected) as caught:
        decode_request(document)
    return caught.value.error_type


def test_valid_request_decodes() -> None:
    assert decode_request(GOOD) == GenerateRequest("abcdefgh", "where is my order", "gist")
    assert decode_request({**GOOD, "mode": "full"}).mode == "full"


@pytest.mark.parametrize(
    "document",
    [
        [],
        "text",
        {},
        {**GOOD, "extra": 1},
        {"session_id": "abcdefgh", "message": "hello"},
        {**GOOD, "mode": "turbo"},
        {**GOOD, "mode": None},
        {**GOOD, "message": 7},
        {**GOOD, "session_id": "short"},
        {**GOOD, "session_id": "abcdefgh\n"},
        {**GOOD, "session_id": "a" * 65},
        {**GOOD, "session_id": "abcdefg h"},
        {**GOOD, "message": "\ud83d"},
        {**GOOD, "message": "ok \udc00 ok"},
        {**GOOD, "message": ""},
        {**GOOD, "message": "  \n\t "},
    ],
)
def test_malformed_request_is_invalid(document: object) -> None:
    assert rejected(document) == "invalid_request"


def test_message_cap_counts_characters_not_bytes() -> None:
    limit = LIMITS.max_message_chars
    assert decode_request({**GOOD, "message": "é" * limit}).message == "é" * limit
    assert decode_request({**GOOD, "message": "😀" * limit}).message == "😀" * limit
    assert rejected({**GOOD, "message": "x" * (limit + 1)}) == "too_long"


def test_limits_agree_with_the_gateway() -> None:
    gateway = json.loads((ROOT / "apps/gateway/limits.json").read_text(encoding="utf-8"))
    assert LIMITS.max_message_chars == gateway["maxMessageChars"]
    assert LIMITS.max_body_bytes == gateway["maxBodyBytes"]
    assert LIMITS.session_id_pattern == gateway["sessionIdPattern"]


def test_the_gateway_never_allows_more_messages_than_the_store_keeps() -> None:
    gateway = json.loads((ROOT / "apps/gateway/limits.json").read_text(encoding="utf-8"))
    assert gateway["maxMessagesPerSession"] <= LIMITS.max_turns_per_session


def test_session_id_cap_matches_its_pattern() -> None:
    longest = "a" * LIMITS.session_id_max_chars
    assert decode_request({**GOOD, "session_id": longest}).session_id == longest
    assert rejected({**GOOD, "session_id": longest + "a"}) == "invalid_request"


def test_schema_carries_the_same_limits() -> None:
    properties = json_schema(GenerateRequest)["properties"]
    assert isinstance(properties, dict)
    assert properties["message"]["maxLength"] == LIMITS.max_message_chars
    assert properties["session_id"]["pattern"] == LIMITS.session_id_pattern
    assert properties["session_id"]["maxLength"] == LIMITS.session_id_max_chars
    assert properties["mode"] == {"enum": ["gist", "full"]}


@pytest.mark.parametrize(
    "document",
    [GOOD, {**GOOD, "extra": 1}, {**GOOD, "mode": "x"}, {**GOOD, "session_id": "short"}],
)
def test_hand_decoder_agrees_with_the_generic_decoder(document: dict[str, object]) -> None:
    try:
        decode_as(GenerateRequest, document)
        expected = True
    except DecodeError:
        expected = False
    try:
        decode_request(document)
        actual = True
    except RequestRejected:
        actual = False
    assert actual == expected


def test_error_types_are_the_agreed_set() -> None:
    assert set(ERROR_TYPES) == {
        "busy",
        "timeout",
        "not_ready",
        "invalid_request",
        "too_long",
        "compare_unavailable",
        "unauthorized",
        "internal",
    }


def test_contract_aggregates_every_wire_shape() -> None:
    required = cast(list[str], json_schema(ServeContract)["required"])
    assert set(required) == {"request", "response", "error", "health"}
    assert ErrorResponse(ErrorInfo("busy", 5)).error.retry_after_s == 5
    assert ErrorInfo("timeout").retry_after_s == 0
    assert HealthReport("ready", 0, 0).status == "ready"
    assert GenerateResponse.__dataclass_fields__["trace"].type in (PublicTrace, "PublicTrace")


def test_limits_loader_rejects_bad_files(tmp_path: Path) -> None:
    good = json.loads((ROOT / "data/serve/limits.json").read_text(encoding="utf-8"))
    cases = [
        {**good, "extra": 1},
        {key: value for key, value in good.items() if key != "maxWaiting"},
        {**good, "maxSessions": 0},
        {**good, "maxSessions": True},
        {**good, "totalDeadlineS": -1},
        {**good, "sessionIdPattern": "("},
        {key: value for key, value in good.items() if key != "ipFailureLimit"},
        {key: value for key, value in good.items() if key != "failureTtlS"},
        {key: value for key, value in good.items() if key != "maxFailureKeys"},
        {**good, "ipFailureLimit": 0},
        {**good, "failureTtlS": 0},
        {**good, "maxFailureKeys": -1},
        {**good, "maxFailureKeys": 1.5},
        {key: value for key, value in good.items() if key != "shopifyTimeoutS"},
        {key: value for key, value in good.items() if key != "shopifyReadAttempts"},
        {**good, "shopifyTimeoutS": 0},
        {**good, "shopifyTimeoutS": -6},
        {**good, "shopifyReadAttempts": 0},
        {**good, "shopifyReadAttempts": 1.5},
        {**good, "shopifyReadAttempts": True},
        {key: value for key, value in good.items() if key != "shopifyRetryS"},
        {**good, "shopifyRetryS": 0},
        {**good, "shopifyRetryS": -0.5},
        {**good, "shopifyRetryS": "0.5"},
        {**good, "shopifyRetryS": True},
        {**good, "shopifyRetryS": None},
        {key: value for key, value in good.items() if key != "shopifyMaxPauseS"},
        {**good, "shopifyMaxPauseS": 0},
        {**good, "shopifyMaxPauseS": -2},
        {**good, "shopifyMaxPauseS": "2"},
        {**good, "shopifyMaxPauseS": True},
        {**good, "shopifyMaxPauseS": None},
    ]
    for index, document in enumerate(cases):
        path = tmp_path / f"limits{index}.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        with pytest.raises(ConfigError):
            load_limits(path)


def test_wire_error_bodies_decode_against_the_contract() -> None:
    busy = {"error": {"type": "busy", "retry_after_s": 5}}
    plain = {"error": {"type": "timeout"}}
    assert decode_as(ErrorResponse, busy) == ErrorResponse(ErrorInfo("busy", 5))
    assert decode_as(ErrorResponse, plain) == ErrorResponse(ErrorInfo("timeout"))


def test_the_retry_hint_has_no_null_in_the_schema() -> None:
    error = cast(dict[str, dict[str, object]], json_schema(ErrorInfo))
    assert error["properties"]["retry_after_s"] == {"type": "integer"}
    assert "retry_after_s" not in cast(list[str], json_schema(ErrorInfo)["required"])
