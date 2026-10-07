from dataclasses import dataclass, field

from gisting.serve.failures import FailureLimits, FailureStore

SESSION = "session-1"
IP = "ip-digest-1"


@dataclass
class Clock:
    now: float = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@dataclass
class Rig:
    clock: Clock = field(default_factory=Clock)
    degraded: list[str] = field(default_factory=lambda: [])
    store: FailureStore = field(init=False)

    def build(self, session: int = 3, ip: int = 5, ttl: float = 100.0, keys: int = 4) -> "Rig":
        limits = FailureLimits(session, ip, ttl, keys)
        self.store = FailureStore(limits, self.clock, self.degraded.append)
        return self
