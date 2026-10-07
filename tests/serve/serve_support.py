import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from gisting.agent.policy import FallbackReason
from gisting.agent.state import TurnResult
from gisting.agent.trace import Traces
from gisting.prompt.messages import Message
from gisting.serve.config import LIMITS
from gisting.serve.failures import FailureLimits, FailureStore
from gisting.serve.gate import Gate, GateLimits
from gisting.serve.scope import TurnScope
from gisting.serve.service import Service
from gisting.serve.store import SessionStore, StoreLimits
from gisting.tools.attempts import FailureCounter
from gisting.tools.policy import load_policy
from gisting.tools.reads import LookupRead, LookupSink

INTERNAL_CANARY = "INTERNAL-CANARY-7f3a"
PATIENCE = 5.0
TOTAL_TOKENS = 321
PUBLIC_TRACE: dict[str, object] = {
    "tools": [],
    "knowledge": [],
    "tokens": {
        "rules": 100,
        "tools": 100,
        "history": 100,
        "tool_results": 0,
        "total": TOTAL_TOKENS,
    },
    "latency": {"first_token_ms": 10.0, "total_ms": 20.0},
}


def record_read(sink: LookupSink, read: LookupRead) -> None:
    sink.begin().finish(read)


def traces(reply_source: str = "template") -> Traces:
    internal: dict[str, object] = {
        "reply_source": reply_source,
        "model_calls": [{"raw_output": INTERNAL_CANARY, "input_messages": [INTERNAL_CANARY]}],
        "canary": INTERNAL_CANARY,
    }
    return Traces(dict(PUBLIC_TRACE), internal)


@dataclass(frozen=True)
class Call:
    mode: str
    session_id: str
    history: tuple[Message, ...]
    failures: FailureCounter
    reads: LookupSink


@dataclass
class FakeTurn:
    replies: list[str] = field(default_factory=lambda: [])
    fallback: FallbackReason | None = None
    failure: BaseException | None = None
    hold: threading.Event | None = None
    calls: list[Call] = field(default_factory=lambda: [])
    started: threading.Event = field(default_factory=threading.Event)
    result_traces: Traces = field(default_factory=traces)
    act: Callable[[Call], None] | None = None

    def __call__(
        self,
        mode: str,
        session_id: str,
        history: list[Message],
        scope: TurnScope,
    ) -> TurnResult:
        call = Call(mode, session_id, tuple(history), scope.failures, scope.reads)
        self.calls.append(call)
        self.started.set()
        if self.act is not None:
            self.act(call)
        if self.hold is not None:
            assert self.hold.wait(PATIENCE)
        if self.failure is not None:
            raise self.failure
        answer = self.replies.pop(0) if self.replies else f"reply {len(self.calls)}"
        return TurnResult(answer, self.fallback, self.result_traces)


def make_service(
    turn: FakeTurn,
    *,
    ready: bool = True,
    total: float = LIMITS.total_deadline_s,
    waiting: int = LIMITS.max_waiting,
    store_limits: StoreLimits | None = None,
) -> Service:
    store = SessionStore(store_limits or StoreLimits.from_limits(LIMITS), time.monotonic)
    gate = Gate(GateLimits(waiting, total, LIMITS.retry_after_s))
    flag = threading.Event()
    if ready:
        flag.set()
    return Service(turn, store, default_failures(), gate, flag, LIMITS.retry_after_s)


def default_failures() -> FailureStore:
    return FailureStore(
        FailureLimits.from_limits(LIMITS, load_policy().failure_limit), time.monotonic
    )
