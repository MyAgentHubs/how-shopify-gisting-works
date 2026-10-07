from dataclasses import dataclass
from enum import StrEnum

from gisting.shopify.jsonvalue import JsonObject
from gisting.tools.outcomes import (
    Found,
    Locked,
    LookupOutcome,
    Mismatch,
    UpstreamError,
)

TOOL_NAME = "lookup_order"


class PublicOutcome(StrEnum):
    COMPLETED = "completed"
    UNAVAILABLE = "unavailable"
    LOCKED = "locked"


@dataclass(frozen=True)
class PublicTrace:
    tool: str
    order_number: str | None
    outcome: PublicOutcome


@dataclass(frozen=True)
class InternalTrace:
    tool: str
    session_id: str
    order_number: str | None
    result_type: str
    cache_hit: bool | None
    detail: str | None
    failures_before: int
    shopify_ms: float | None = None


@dataclass(frozen=True)
class Trace:
    internal: InternalTrace
    public: PublicTrace


def public_outcome(outcome: LookupOutcome) -> PublicOutcome:
    if isinstance(outcome, UpstreamError):
        return PublicOutcome.UNAVAILABLE
    if isinstance(outcome, Locked):
        return PublicOutcome.LOCKED
    return PublicOutcome.COMPLETED


def outcome_detail(outcome: LookupOutcome) -> str | None:
    if isinstance(outcome, Mismatch):
        return outcome.stage.value
    if isinstance(outcome, UpstreamError):
        return outcome.reason
    return None


def result_type(outcome: LookupOutcome) -> str:
    return "Found" if isinstance(outcome, Found) else type(outcome).__name__


def public_json(trace: PublicTrace) -> JsonObject:
    return {
        "tool": trace.tool,
        "order_number": trace.order_number,
        "outcome": trace.outcome.value,
    }


def internal_json(trace: InternalTrace) -> JsonObject:
    return {
        "tool": trace.tool,
        "session_id": trace.session_id,
        "order_number": trace.order_number,
        "result_type": trace.result_type,
        "cache_hit": trace.cache_hit,
        "detail": trace.detail,
        "failures_before": trace.failures_before,
        "shopify_ms": trace.shopify_ms,
    }
