from dataclasses import dataclass, field
from enum import StrEnum

from gisting.shopify.jsonvalue import Json, JsonObject, object_items


class Cause(StrEnum):
    WRONG_STORE = "wrong_store"
    ORDER_NOT_FOUND = "order_not_found"
    DUPLICATE_ORDER = "duplicate_order"
    NOT_TEST_ORDER = "not_test_order"
    MISSING_BATCH_TAG = "missing_batch_tag"
    UNVERIFIED_ORDER = "unverified_order"
    FOREIGN_ID = "foreign_id"
    UNKNOWN_DOCUMENT = "unknown_document"
    WRONG_DOCUMENT_KIND = "wrong_document_kind"
    CLI_UNAVAILABLE = "cli_unavailable"
    LOCAL_IO = "local_io"
    READ_ONLY = "read_only"
    NETWORK = "network"
    AUTH = "auth"
    RATE_LIMITED = "rate_limited"
    HTTP_STATUS = "http_status"


@dataclass(frozen=True)
class Ok:
    data: JsonObject
    throttle: JsonObject | None = field(default=None, compare=False)


@dataclass(frozen=True)
class NotExecuted:
    cause: Cause
    detail: str = ""


@dataclass(frozen=True)
class Uncertain:
    reason: str


@dataclass(frozen=True)
class GraphQLError:
    errors: tuple[JsonObject, ...]
    user_errors: bool = False
    throttle: JsonObject | None = field(default=None, compare=False)


Result = Ok | NotExecuted | Uncertain | GraphQLError
Failure = NotExecuted | Uncertain | GraphQLError


def error_objects(value: Json) -> tuple[JsonObject, ...]:
    if not isinstance(value, list):
        return ()
    try:
        return tuple(object_items(value, "errors"))
    except ValueError:
        return ({"message": "unparseable errors"},)


def classify_payload(payload: Json) -> Result:
    if not isinstance(payload, dict):
        return Uncertain("response is not a JSON object")
    errors = error_objects(payload.get("errors"))
    if errors:
        return GraphQLError(errors)
    data = payload.get("data", payload)
    if not isinstance(data, dict):
        return Uncertain("response has no data object")
    return Ok(data)


def user_errors(data: JsonObject) -> tuple[JsonObject, ...]:
    found: list[JsonObject] = []
    for payload in data.values():
        if isinstance(payload, dict):
            found.extend(error_objects(payload.get("userErrors")))
    return tuple(found)
