from collections import Counter
from typing import Protocol


class FailureCounter(Protocol):
    def failures(self, session_id: str) -> int: ...

    def is_locked(self, session_id: str) -> bool: ...

    def record_failure(self, session_id: str) -> None: ...


class InMemoryFailureCounter:
    def __init__(self, limit: int) -> None:
        self._limit = limit
        self._counts: Counter[str] = Counter()

    def failures(self, session_id: str) -> int:
        return self._counts[session_id]

    def is_locked(self, session_id: str) -> bool:
        return self._counts[session_id] >= self._limit

    def record_failure(self, session_id: str) -> None:
        self._counts[session_id] += 1
