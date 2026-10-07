import re
from dataclasses import dataclass
from typing import Annotated, Literal, cast, get_args

from gisting.agent.public_trace import PublicTrace
from gisting.prompt.schema_marks import MaxLength, Pattern
from gisting.serve.config import LIMITS

Mode = Literal["gist", "full"]
ErrorType = Literal[
    "busy",
    "timeout",
    "not_ready",
    "invalid_request",
    "too_long",
    "compare_unavailable",
    "unauthorized",
    "internal",
]
ReadyStatus = Literal["ready", "loading"]
ERROR_TYPES: tuple[str, ...] = get_args(ErrorType)
MODES: tuple[str, ...] = get_args(Mode)
SessionId = Annotated[
    str, Pattern(LIMITS.session_id_pattern), MaxLength(LIMITS.session_id_max_chars)
]
MessageText = Annotated[str, MaxLength(LIMITS.max_message_chars)]
REQUEST_KEYS: frozenset[object] = frozenset({"session_id", "message", "mode"})


@dataclass(frozen=True)
class GenerateRequest:
    session_id: SessionId
    message: MessageText
    mode: Mode


@dataclass(frozen=True)
class GenerateResponse:
    answer: str
    trace: PublicTrace


@dataclass(frozen=True)
class ErrorInfo:
    type: ErrorType
    retry_after_s: int = 0


@dataclass(frozen=True)
class ErrorResponse:
    error: ErrorInfo


@dataclass(frozen=True)
class HealthReport:
    status: ReadyStatus
    running: int
    waiting: int


@dataclass(frozen=True)
class ServeContract:
    request: GenerateRequest
    response: GenerateResponse
    error: ErrorResponse
    health: HealthReport


RejectionType = Literal["invalid_request", "too_long"]


class RequestRejected(ValueError):
    def __init__(self, error_type: RejectionType) -> None:
        super().__init__(error_type)
        self.error_type: RejectionType = error_type


def invalid() -> RequestRejected:
    return RequestRejected("invalid_request")


def text_field(document: dict[object, object], name: str) -> str:
    value = document[name]
    if not isinstance(value, str):
        raise invalid()
    return value


def check_session_id(value: str) -> None:
    if len(value) > LIMITS.session_id_max_chars:
        raise invalid()
    if re.fullmatch(LIMITS.session_id_pattern, value) is None:
        raise invalid()


def check_message(value: str) -> None:
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise invalid() from error
    if not value.strip():
        raise invalid()
    if len(value) > LIMITS.max_message_chars:
        raise RequestRejected("too_long")


def decode_request(document: object) -> GenerateRequest:
    if not isinstance(document, dict):
        raise invalid()
    entries = cast(dict[object, object], document)
    if frozenset(entries) != REQUEST_KEYS:
        raise invalid()
    session_id = text_field(entries, "session_id")
    message = text_field(entries, "message")
    mode = text_field(entries, "mode")
    check_session_id(session_id)
    if mode not in MODES:
        raise invalid()
    check_message(message)
    return GenerateRequest(session_id, message, cast(Mode, mode))
