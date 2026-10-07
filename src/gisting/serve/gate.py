import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Generic, TypeVar, cast

from gisting.serve.config import Limits
from gisting.serve.deadline import Deadline, DeadlineExceeded

T = TypeVar("T")
R = TypeVar("R")
CLOSE_WAIT_S = 1.0


@dataclass(frozen=True)
class GateLimits:
    max_waiting: int
    total_deadline_s: float
    retry_after_s: int

    @classmethod
    def from_limits(cls, limits: Limits) -> "GateLimits":
        return cls(limits.max_waiting, limits.total_deadline_s, limits.retry_after_s)


@dataclass(frozen=True)
class GateStats:
    running: int
    waiting: int
    healthy: bool = True


@dataclass(frozen=True)
class Completed(Generic[T]):
    value: T


@dataclass(frozen=True)
class Busy:
    retry_after_s: int


@dataclass(frozen=True)
class TimedOut:
    pass


@dataclass(frozen=True)
class Failed:
    error_type: str


Outcome = Completed[T] | Busy | TimedOut | Failed


class JobFailed(Exception):
    def __init__(self, error_type: str) -> None:
        super().__init__(error_type)
        self.error_type = error_type


def guarded(call: Callable[[], R]) -> R:
    try:
        return call()
    except DeadlineExceeded:
        raise
    except BaseException as error:
        raise JobFailed(type(error).__name__) from error


@dataclass
class Ticket:
    job: Callable[[Deadline], object]
    settle: Callable[[object], None]
    deadline: Deadline
    done: threading.Event = field(default_factory=threading.Event)
    outcome: Outcome[object] | None = None
    abandoned: bool = False


class Gate:
    def __init__(self, limits: GateLimits, clock: Callable[[], float] = time.monotonic) -> None:
        self._limits = limits
        self._clock = clock
        self._cond = threading.Condition()
        self._queue: deque[Ticket] = deque()
        self._running = False
        self._current: Ticket | None = None
        self._closed = False
        self._worker = threading.Thread(target=self._loop, name="serve-gate", daemon=True)
        self._worker.start()

    def stats(self) -> GateStats:
        with self._cond:
            return GateStats(int(self._running), len(self._queue), self._healthy())

    def close(self) -> None:
        with self._cond:
            self._closed = True
            self._cond.notify_all()
        self._worker.join(CLOSE_WAIT_S)

    def _healthy(self) -> bool:
        if self._closed or not self._worker.is_alive():
            return False
        return not (self._current is not None and self._current.deadline.expired())

    def submit(self, job: Callable[[Deadline], T], settle: Callable[[T], None]) -> Outcome[T]:
        deadline = Deadline(self._clock() + self._limits.total_deadline_s, self._clock)
        ticket = Ticket(job, lambda value: settle(cast(T, value)), deadline)
        with self._cond:
            if self._closed or not self._worker.is_alive():
                return Failed("WorkerStopped")
            if len(self._queue) + int(self._running) > self._limits.max_waiting:
                return Busy(self._limits.retry_after_s)
            self._queue.append(ticket)
            self._cond.notify_all()
        ticket.done.wait(deadline.remaining())
        return cast(Outcome[T], self._collect(ticket))

    def _collect(self, ticket: Ticket) -> Outcome[object]:
        with self._cond:
            if ticket.outcome is not None:
                return ticket.outcome
            ticket.abandoned = True
            if ticket in self._queue:
                self._queue.remove(ticket)
            return TimedOut()

    def _loop(self) -> None:
        while (ticket := self._take()) is not None:
            outcome: Outcome[object] = Failed("WorkerInterrupted")
            try:
                outcome = self._execute(ticket)
            finally:
                with self._cond:
                    self._complete(ticket, outcome)
                    self._running = False
                    self._current = None

    def _take(self) -> Ticket | None:
        with self._cond:
            while not self._closed:
                ticket = self._next_ready()
                if ticket is not None:
                    self._running = True
                    self._current = ticket
                    return ticket
                self._cond.wait()
            return None

    def _next_ready(self) -> Ticket | None:
        while self._queue:
            ticket = self._queue.popleft()
            if ticket.abandoned:
                continue
            if not ticket.deadline.expired():
                return ticket
            self._complete(ticket, TimedOut())
        return None

    def _complete(self, ticket: Ticket, outcome: Outcome[object]) -> None:
        if ticket.outcome is None:
            ticket.outcome = outcome
            ticket.done.set()

    def _execute(self, ticket: Ticket) -> Outcome[object]:
        try:
            value = guarded(lambda: ticket.job(ticket.deadline))
            return self._deliver(ticket, value)
        except DeadlineExceeded:
            return TimedOut()
        except JobFailed as failure:
            return Failed(failure.error_type)

    def _deliver(self, ticket: Ticket, value: object) -> Outcome[object]:
        with self._cond:
            if ticket.abandoned or ticket.deadline.expired():
                return TimedOut()
            guarded(lambda: ticket.settle(value))
            outcome = Completed(value)
            self._complete(ticket, outcome)
            return outcome
