import threading

from gisting.serve.deadline import Deadline
from gisting.serve.gate import Completed, Gate, GateLimits

PATIENCE = 5.0
CALLERS = 6
GATE_THREAD = "serve-gate"
TICK = threading.Event()


def gate_threads() -> int:
    return sum(1 for thread in threading.enumerate() if thread.name == GATE_THREAD)


class Overlap:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.active = 0
        self.peak = 0

    def __call__(self, deadline: Deadline) -> str:
        with self.lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
        TICK.wait(0.02)
        with self.lock:
            self.active -= 1
        return "done"


def test_a_gate_starts_exactly_one_worker_thread() -> None:
    before = gate_threads()
    gate = Gate(GateLimits(CALLERS, 20.0, 5))
    assert gate_threads() == before + 1
    gate.close()


def test_concurrent_callers_never_run_their_jobs_at_the_same_time() -> None:
    gate = Gate(GateLimits(CALLERS, 20.0, 5))
    overlap = Overlap()
    outcomes: list[object] = []
    callers = [
        threading.Thread(target=lambda: outcomes.append(gate.submit(overlap, lambda _v: None)))
        for _ in range(CALLERS)
    ]
    for caller in callers:
        caller.start()
    for caller in callers:
        caller.join(PATIENCE)
    gate.close()
    assert outcomes == [Completed("done")] * CALLERS
    assert overlap.peak == 1
