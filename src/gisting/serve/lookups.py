import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from gisting.serve.deadline import DeadlineExceeded
from gisting.tools.millis import round_ms, seconds_to_ms
from gisting.tools.reads import LookupRead

CUT_OFF = DeadlineExceeded.__name__


@dataclass
class Slot:
    owner: "LookupReads"
    started: float
    read: LookupRead | None = None

    def finish(self, read: LookupRead) -> None:
        self.owner.settle(self, read)

    def interrupt(self, error_type: str) -> None:
        self.owner.settle(self, self.owner.elapsed(self.started, error_type))


class LookupReads:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._slots: list[Slot] = []

    def begin(self) -> Slot:
        with self._lock:
            slot = Slot(self, self._clock())
            self._slots.append(slot)
            return slot

    def settle(self, slot: Slot, read: LookupRead) -> None:
        with self._lock:
            slot.read = read

    def elapsed(self, started: float, result_type: str) -> LookupRead:
        spent_ms = round_ms(seconds_to_ms(self._clock() - started))
        return LookupRead(spent_ms, result_type, False)

    def snapshot(self) -> tuple[LookupRead, ...]:
        with self._lock:
            return tuple(self._read_of(slot) for slot in self._slots)

    def _read_of(self, slot: Slot) -> LookupRead:
        return slot.read if slot.read is not None else self.elapsed(slot.started, CUT_OFF)
