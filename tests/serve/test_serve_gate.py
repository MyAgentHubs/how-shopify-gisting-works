import threading
from dataclasses import dataclass, field

import pytest

from gisting.serve.config import LIMITS
from gisting.serve.deadline import Deadline, DeadlineExceeded
from gisting.serve.gate import (
    Busy,
    Completed,
    Failed,
    Gate,
    GateLimits,
    Outcome,
    TimedOut,
)

PATIENCE = 5.0
TICK = threading.Event()


@dataclass
class Clock:
    now: float = 0.0

    def __call__(self) -> float:
        return self.now


@dataclass
class Controlled:
    name: str
    log: list[str]
    failure: BaseException | None = None
    started: threading.Event = field(default_factory=threading.Event)
    release: threading.Event = field(default_factory=threading.Event)

    def __call__(self, deadline: Deadline) -> str:
        self.log.append(self.name)
        self.started.set()
        assert self.release.wait(PATIENCE)
        if self.failure is not None:
            raise self.failure
        return self.name


@dataclass
class Submission:
    gate: Gate
    job: Controlled
    settled: list[str]
    outcome: Outcome[str] | None = None
    thread: threading.Thread | None = None

    def start(self) -> "Submission":
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()
        return self

    def run(self) -> None:
        self.outcome = self.gate.submit(self.job, self.settled.append)

    def finish(self) -> Outcome[str] | None:
        assert self.thread is not None
        self.thread.join(PATIENCE)
        assert not self.thread.is_alive()
        return self.outcome


def make_gate(waiting: int = 2, total: float = 20.0, clock: Clock | None = None) -> Gate:
    limits = GateLimits(waiting, total, 7)
    return Gate(limits, clock) if clock else Gate(limits)


def wait_until(gate: Gate, running: int, waiting: int) -> None:
    for _ in range(5000):
        stats = gate.stats()
        if (stats.running, stats.waiting) == (running, waiting):
            return
        TICK.wait(0.001)
    message = f"gate stuck at {gate.stats()}"
    raise AssertionError(message)


def test_limits_come_from_the_data_file() -> None:
    limits = GateLimits.from_limits(LIMITS)
    assert limits == GateLimits(LIMITS.max_waiting, LIMITS.total_deadline_s, LIMITS.retry_after_s)


def test_a_lone_request_runs_and_settles() -> None:
    gate = make_gate()
    log: list[str] = []
    settled: list[str] = []
    job = Controlled("only", log)
    job.release.set()
    assert gate.submit(job, settled.append) == Completed("only")
    assert settled == ["only"]
    assert gate.stats().running == 0
    gate.close()


def test_overflow_is_busy_at_once_and_waiters_run_in_arrival_order() -> None:
    gate = make_gate(waiting=2)
    log: list[str] = []
    settled: list[str] = []
    jobs = [Controlled(f"job{index}", log) for index in range(5)]
    first = Submission(gate, jobs[0], settled).start()
    assert jobs[0].started.wait(PATIENCE)
    second = Submission(gate, jobs[1], settled).start()
    wait_until(gate, 1, 1)
    third = Submission(gate, jobs[2], settled).start()
    wait_until(gate, 1, 2)
    overflow = [Submission(gate, jobs[index], settled).start() for index in (3, 4)]
    assert [item.finish() for item in overflow] == [Busy(7), Busy(7)]
    for job in jobs:
        job.release.set()
    assert [item.finish() for item in (first, second, third)] == [
        Completed("job0"),
        Completed("job1"),
        Completed("job2"),
    ]
    assert log == ["job0", "job1", "job2"]
    assert settled == ["job0", "job1", "job2"]
    wait_until(gate, 0, 0)
    gate.close()


def test_a_waiter_that_runs_out_of_time_never_runs_and_frees_its_place() -> None:
    gate = make_gate(waiting=1, total=0.2)
    log: list[str] = []
    settled: list[str] = []
    blocker = Controlled("blocker", log)
    running = Submission(gate, blocker, settled).start()
    assert blocker.started.wait(PATIENCE)
    patient = Controlled("patient", log)
    patient.release.set()
    waiter = Submission(gate, patient, settled).start()
    assert waiter.finish() == TimedOut()
    assert log == ["blocker"]
    assert gate.stats().waiting == 0
    blocker.release.set()
    assert running.finish() in (TimedOut(), Completed("blocker"))
    wait_until(gate, 0, 0)
    after = Controlled("after", log)
    after.release.set()
    assert gate.submit(after, settled.append) == Completed("after")
    gate.close()


def test_a_running_turn_that_times_out_is_discarded_and_holds_the_slot_until_it_returns() -> None:
    gate = make_gate(waiting=1, total=0.2)
    log: list[str] = []
    settled: list[str] = []
    slow = Controlled("slow", log)
    caller = Submission(gate, slow, settled).start()
    assert slow.started.wait(PATIENCE)
    assert caller.finish() == TimedOut()
    assert gate.stats().running == 1
    queued = Controlled("queued", log)
    queued.release.set()
    blocked = Submission(gate, queued, settled).start()
    assert blocked.finish() == TimedOut()
    assert log == ["slow"]
    slow.release.set()
    wait_until(gate, 0, 0)
    assert settled == []
    follow = Controlled("follow", log)
    follow.release.set()
    assert gate.submit(follow, settled.append) == Completed("follow")
    assert settled == ["follow"]
    gate.close()


def test_a_job_that_finishes_after_the_deadline_is_not_settled() -> None:
    clock = Clock()
    gate = make_gate(total=10.0, clock=clock)
    settled: list[str] = []

    def late(deadline: Deadline) -> str:
        clock.now = 11.0
        return "late"

    assert gate.submit(late, settled.append) == TimedOut()
    assert settled == []
    assert gate.submit(lambda deadline: "next", settled.append) == Completed("next")
    assert settled == ["next"]
    gate.close()


def test_a_deadline_error_from_the_job_is_a_timeout() -> None:
    gate = make_gate()
    settled: list[str] = []

    def abort(deadline: Deadline) -> str:
        raise DeadlineExceeded

    assert gate.submit(abort, settled.append) == TimedOut()
    assert settled == []
    gate.close()


def test_a_failing_job_reports_its_type_and_the_gate_recovers() -> None:
    gate = make_gate()
    log: list[str] = []
    settled: list[str] = []
    broken = Controlled("broken", log, failure=ValueError("secret text"))
    broken.release.set()
    outcome = gate.submit(broken, settled.append)
    assert outcome == Failed("ValueError")
    assert "secret" not in repr(outcome)
    assert settled == []
    assert (gate.stats().running, gate.stats().waiting) == (0, 0)
    fine = Controlled("fine", log)
    fine.release.set()
    assert gate.submit(fine, settled.append) == Completed("fine")
    gate.close()


def test_a_failing_settle_is_a_failure_and_the_gate_recovers() -> None:
    gate = make_gate()

    def explode(value: str) -> None:
        raise KeyError(value)

    assert gate.submit(lambda deadline: "x", explode) == Failed("KeyError")
    assert gate.submit(lambda deadline: "y", lambda value: None) == Completed("y")
    gate.close()


def test_many_threads_never_deadlock_and_every_outcome_is_accounted_for() -> None:
    gate = make_gate(waiting=2, total=PATIENCE)
    settled: list[str] = []
    outcomes: list[Outcome[str]] = []
    guard = threading.Lock()

    def call(index: int) -> None:
        outcome = gate.submit(lambda deadline: f"r{index}", settled.append)
        with guard:
            outcomes.append(outcome)

    threads = [threading.Thread(target=call, args=(index,), daemon=True) for index in range(60)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(PATIENCE * 2)
        assert not thread.is_alive()
    completed = [item for item in outcomes if isinstance(item, Completed)]
    busy = [item for item in outcomes if isinstance(item, Busy)]
    assert len(completed) + len(busy) == 60
    assert len(completed) >= 1
    assert sorted(settled) == sorted(item.value for item in completed)
    assert (gate.stats().running, gate.stats().waiting) == (0, 0)
    gate.close()


class Interrupt(BaseException):
    pass


@pytest.mark.parametrize("failure", [Interrupt(), SystemExit(1), KeyboardInterrupt()])
def test_a_base_exception_in_a_job_fails_it_and_the_worker_lives_on(
    failure: BaseException,
) -> None:
    gate = make_gate(total=PATIENCE)
    settled: list[str] = []

    def explode(deadline: Deadline) -> str:
        raise failure

    assert gate.submit(explode, settled.append) == Failed(type(failure).__name__)
    wait_until(gate, 0, 0)
    assert gate.stats().healthy
    results = [gate.submit(lambda deadline: "ok", settled.append) for _ in range(4)]
    assert results == [Completed("ok")] * 4
    gate.close()


def test_a_base_exception_in_settle_fails_the_job_and_the_worker_lives_on() -> None:
    gate = make_gate(total=PATIENCE)

    def exit_now(value: str) -> None:
        raise SystemExit(2)

    assert gate.submit(lambda deadline: "x", exit_now) == Failed("SystemExit")
    assert gate.submit(lambda deadline: "y", lambda value: None) == Completed("y")
    gate.close()


def test_a_job_still_running_past_the_deadline_makes_the_gate_unhealthy_until_it_returns() -> None:
    gate = make_gate(waiting=1, total=0.2)
    log: list[str] = []
    slow = Controlled("slow", log)
    caller = Submission(gate, slow, []).start()
    assert slow.started.wait(PATIENCE)
    assert caller.finish() == TimedOut()
    assert gate.stats().healthy is False
    slow.release.set()
    wait_until(gate, 0, 0)
    assert gate.stats().healthy
    gate.close()


def test_a_running_job_inside_its_deadline_is_healthy() -> None:
    gate = make_gate(total=PATIENCE)
    job = Controlled("busy", [])
    runner = Submission(gate, job, []).start()
    assert job.started.wait(PATIENCE)
    assert gate.stats().healthy
    job.release.set()
    assert runner.finish() == Completed("busy")
    gate.close()


def test_a_closed_gate_is_unhealthy_and_refuses_work() -> None:
    gate = make_gate()
    gate.close()
    assert gate.stats().healthy is False
    assert gate.submit(lambda deadline: "x", lambda value: None) == Failed("WorkerStopped")


def test_settle_runs_under_the_same_lock_that_decides_a_timeout() -> None:
    gate = make_gate(total=0.2)
    committed: list[str] = []
    settling = threading.Event()
    release = threading.Event()

    def settle(value: str) -> None:
        settling.set()
        assert release.wait(PATIENCE)
        committed.append(value)

    job = Controlled("late", [])
    job.release.set()
    caller = Submission(gate, job, committed)
    caller.settled = committed
    outcomes: list[Outcome[str]] = []
    thread = threading.Thread(target=lambda: outcomes.append(gate.submit(job, settle)), daemon=True)
    thread.start()
    assert settling.wait(PATIENCE)
    TICK.wait(0.5)
    release.set()
    thread.join(PATIENCE)
    assert not thread.is_alive()
    assert outcomes == [Completed("late")]
    assert committed == ["late"]
    gate.close()


def test_a_commit_is_never_made_for_a_caller_that_has_already_been_told_timeout() -> None:
    clock = Clock()
    gate = make_gate(total=0.2, clock=clock)
    committed: list[str] = []
    job = Controlled("late", [])
    caller = Submission(gate, job, committed).start()
    assert job.started.wait(PATIENCE)
    assert caller.finish() == TimedOut()
    assert not clock.now
    job.release.set()
    wait_until(gate, 0, 0)
    assert committed == []
    gate.close()
