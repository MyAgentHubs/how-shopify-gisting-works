import time
from collections.abc import Callable
from dataclasses import dataclass, field

from gisting.shopify.client import AdminClient
from gisting.shopify.demo_email import demo_email
from gisting.shopify.jsonvalue import Json, JsonObject
from gisting.shopify.order_state import OrderState
from gisting.shopify.results import Cause, Failure, NotExecuted, Uncertain
from gisting.tools.attempts import FailureCounter
from gisting.tools.cache import OrderCache
from gisting.tools.facts import build_facts
from gisting.tools.millis import round_ms, seconds_to_ms
from gisting.tools.outcomes import (
    NO_MATCH_TYPES,
    Found,
    Locked,
    LookupOutcome,
    Malformed,
    Mismatch,
    MismatchStage,
    NotDemoOrder,
    NotFound,
    OutOfRange,
    UpstreamError,
)
from gisting.tools.policy import LookupPolicy
from gisting.tools.reads import DISCARD, LookupRead, LookupSink, OpenRead
from gisting.tools.render import render_result
from gisting.tools.trace import (
    TOOL_NAME,
    InternalTrace,
    PublicTrace,
    Trace,
    outcome_detail,
    public_outcome,
    result_type,
)
from gisting.tools.verification import email_matches, in_range, parse_order_name


@dataclass(frozen=True)
class LookupDeps:
    client: AdminClient
    cache: OrderCache
    attempts: FailureCounter
    policy: LookupPolicy
    email_secret: str = field(repr=False)
    clock: Callable[[], float] = time.monotonic
    reads: LookupSink = DISCARD


@dataclass(frozen=True)
class ToolResponse:
    result: JsonObject
    trace: Trace


@dataclass(frozen=True)
class Resolved:
    outcome: LookupOutcome
    order_number: str | None = None
    cache_hit: bool | None = None
    shopify_ms: float | None = None


def text_argument(arguments: JsonObject, key: str) -> str:
    value: Json = arguments.get(key)
    return value if isinstance(value, str) else ""


def upstream_failure(failure: Failure) -> NotFound | UpstreamError:
    if isinstance(failure, NotExecuted):
        if failure.cause is Cause.ORDER_NOT_FOUND:
            return NotFound()
        return UpstreamError(failure.cause.value)
    if isinstance(failure, Uncertain):
        return UpstreamError("uncertain")
    return UpstreamError("graphql_error")


class LookupOrder:
    def __init__(self, deps: LookupDeps) -> None:
        self._deps = deps

    def call(self, arguments: JsonObject, session_id: str) -> ToolResponse:
        open_read = self._deps.reads.begin()
        try:
            resolved, failures = self._settle(arguments, session_id)
        except BaseException as error:
            open_read.interrupt(type(error).__name__)
            raise
        return self._respond(resolved, session_id, failures, open_read)

    def _settle(self, arguments: JsonObject, session_id: str) -> tuple[Resolved, int]:
        failures = self._deps.attempts.failures(session_id)
        if self._deps.attempts.is_locked(session_id):
            resolved = Resolved(Locked())
        else:
            resolved = self._resolve(
                text_argument(arguments, "order_number"), text_argument(arguments, "email")
            )
        if isinstance(resolved.outcome, NO_MATCH_TYPES):
            self._deps.attempts.record_failure(session_id)
        return resolved, failures

    def _resolve(self, raw_number: str, email: str) -> Resolved:
        name = parse_order_name(raw_number)
        if isinstance(name, Malformed):
            return Resolved(name)
        if not in_range(name, self._deps.policy):
            return Resolved(OutOfRange(), name)
        expected = demo_email(self._deps.email_secret, name)
        if not email_matches(expected, email):
            return Resolved(Mismatch(MismatchStage.INPUT_EMAIL), name)
        return self._verified(name, email)

    def _verified(self, name: str, email: str) -> Resolved:
        cached = self._deps.cache.get(name)
        hit = cached is not None
        order, shopify_ms = (cached, None) if cached is not None else self._fetch(name)
        if not isinstance(order, OrderState):
            return Resolved(order, name, hit, shopify_ms)
        if not hit:
            self._deps.cache.put(name, order)
        if not self._is_demo_order(order):
            return Resolved(NotDemoOrder(), name, hit, shopify_ms)
        if order.email is None or not email_matches(order.email, email):
            return Resolved(Mismatch(MismatchStage.READBACK_EMAIL), name, hit, shopify_ms)
        found = Found(build_facts(order, self._deps.policy.sources))
        return Resolved(found, name, hit, shopify_ms)

    def _is_demo_order(self, order: OrderState) -> bool:
        return order.test and set(self._deps.policy.required_tags) <= set(order.tags)

    def _fetch(self, name: str) -> tuple[OrderState | NotFound | UpstreamError, float]:
        started = self._deps.clock()
        fetched = self._deps.client.fetch_order(name)
        elapsed_ms = round_ms(seconds_to_ms(self._deps.clock() - started))
        outcome = fetched if isinstance(fetched, OrderState) else upstream_failure(fetched)
        return outcome, elapsed_ms

    def _respond(
        self, resolved: Resolved, session_id: str, failures: int, open_read: OpenRead
    ) -> ToolResponse:
        outcome = resolved.outcome
        internal = InternalTrace(
            tool=TOOL_NAME,
            session_id=session_id,
            order_number=resolved.order_number,
            result_type=result_type(outcome),
            cache_hit=resolved.cache_hit,
            detail=outcome_detail(outcome),
            failures_before=failures,
            shopify_ms=resolved.shopify_ms,
        )
        public = PublicTrace(TOOL_NAME, resolved.order_number, public_outcome(outcome))
        open_read.finish(LookupRead(resolved.shopify_ms, internal.result_type, resolved.cache_hit))
        return ToolResponse(render_result(outcome), Trace(internal, public))
