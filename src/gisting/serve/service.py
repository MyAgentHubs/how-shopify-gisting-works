import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Protocol, cast

from gisting.agent.public_trace import PublicTrace
from gisting.agent.state import TurnResult
from gisting.agent.trace import ReplySource
from gisting.prompt.messages import AssistantMessage, Message, UserMessage
from gisting.serve.contract import ErrorType, GenerateRequest, HealthReport, Mode
from gisting.serve.deadline import Deadline
from gisting.serve.failures import FailureSnapshot, FailureStore, FailureView, LiveFailures
from gisting.serve.gate import Busy, Completed, Failed, Gate, Outcome
from gisting.serve.lookups import LookupReads
from gisting.serve.scope import TurnScope
from gisting.serve.store import CompareUnavailable, Exchange, SessionStore
from gisting.serve.strict import round_trip
from gisting.tools.millis import seconds_to_ms
from gisting.tools.reads import LookupRead

REPLY_SOURCES = frozenset(source.value for source in ReplySource)


class TurnFunction(Protocol):
    def __call__(
        self,
        mode: Mode,
        session_id: str,
        history: list[Message],
        scope: TurnScope,
    ) -> TurnResult: ...


@dataclass(frozen=True)
class Served:
    answer: str
    trace: Mapping[str, object]
    reply_source: str | None = None
    fallback_reason: str | None = None
    tokens: int | None = None
    lookups: tuple[LookupRead, ...] = ()


@dataclass(frozen=True)
class Refused:
    error_type: ErrorType
    retry_after_s: int | None = None
    detail: str | None = None
    lookups: tuple[LookupRead, ...] = ()


@dataclass
class Timing:
    queue_ms: float | None = None
    run_ms: float | None = None
    session_reset: bool = False


@dataclass
class Pending:
    request: GenerateRequest
    ip_digest: str | None
    entered: float
    timing: Timing = field(default_factory=Timing)
    reads: LookupReads = field(default_factory=LookupReads)
    failures_before: FailureSnapshot = field(default_factory=lambda: FailureSnapshot({}))


@dataclass(frozen=True)
class Handled:
    result: Served | Refused
    timing: Timing


def to_messages(exchanges: tuple[Exchange, ...]) -> list[Message]:
    messages: list[Message] = []
    for exchange in exchanges:
        messages.extend((UserMessage(exchange.user), AssistantMessage(exchange.assistant)))
    return messages


def known_reply_source(internal: Mapping[str, object]) -> str | None:
    value = internal.get("reply_source")
    return value if isinstance(value, str) and value in REPLY_SOURCES else None


def total_tokens(trace: Mapping[str, object]) -> int | None:
    tokens = trace.get("tokens")
    total = cast(Mapping[str, object], tokens).get("total") if isinstance(tokens, dict) else None
    return total if type(total) is int else None


def serve(result: TurnResult, lookups: tuple[LookupRead, ...]) -> Served:
    public = result.traces.public
    trace = round_trip(PublicTrace, public)
    reason = result.fallback_reason.value if result.fallback_reason else None
    return Served(
        result.answer,
        trace,
        known_reply_source(result.traces.internal),
        reason,
        total_tokens(trace),
        lookups,
    )


@dataclass
class Service:
    turn: TurnFunction
    store: SessionStore
    failures: FailureStore
    gate: Gate
    ready: threading.Event
    retry_after_s: int
    clock: Callable[[], float] = field(default=time.monotonic)

    def health(self) -> HealthReport:
        stats = self.gate.stats()
        status = "ready" if self.ready.is_set() and stats.healthy else "loading"
        return HealthReport(status, stats.running, stats.waiting)

    def handle(self, request: GenerateRequest, ip_digest: str | None = None) -> Handled:
        pending = Pending(request, ip_digest, self.clock())
        if self.health().status != "ready":
            return Handled(Refused("not_ready", self.retry_after_s), pending.timing)

        def job(deadline: Deadline) -> Served | Refused:
            return self.run(pending, deadline)

        def settle(value: Served | Refused) -> None:
            if isinstance(value, Served) and request.mode == "gist":
                done = self.store.commit(
                    request.session_id, request.message, value.answer, pending.failures_before
                )
                pending.timing.session_reset = done.reset

        return Handled(
            self.refusal_or_served(self.gate.submit(job, settle), pending), pending.timing
        )

    def run(self, pending: Pending, deadline: Deadline) -> Served | Refused:
        started = self.clock()
        pending.timing.queue_ms = seconds_to_ms(started - pending.entered)
        try:
            prepared = self.prepare(pending)
            if prepared is None:
                return Refused("compare_unavailable")
            exchanges, view = prepared
            request = pending.request
            messages = [*to_messages(exchanges), UserMessage(request.message)]
            result = self.turn(
                request.mode,
                request.session_id,
                messages,
                TurnScope(deadline, view, pending.reads),
            )
            if isinstance(view, LiveFailures):
                pending.failures_before = view.before()
            return serve(result, pending.reads.snapshot())
        finally:
            pending.timing.run_ms = seconds_to_ms(self.clock() - started)

    def prepare(self, pending: Pending) -> tuple[tuple[Exchange, ...], FailureView] | None:
        request = pending.request
        if request.mode == "gist":
            history = self.store.history(request.session_id)
            return history, self.failures.live(pending.ip_digest)
        compare = self.store.compare_history(request.session_id, request.message)
        if isinstance(compare, CompareUnavailable):
            return None
        return compare.exchanges, self.failures.replay(pending.ip_digest, compare.failures)

    def refusal_or_served(
        self, outcome: Outcome[Served | Refused], pending: Pending
    ) -> Served | Refused:
        if isinstance(outcome, Completed):
            return outcome.value
        if isinstance(outcome, Busy):
            return Refused("busy", outcome.retry_after_s)
        if isinstance(outcome, Failed):
            return Refused("internal", detail=outcome.error_type, lookups=pending.reads.snapshot())
        return Refused("timeout", lookups=pending.reads.snapshot())
