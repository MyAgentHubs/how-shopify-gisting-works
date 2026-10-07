from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Generation:
    text: str
    ids: tuple[int, ...]
    first_token_ms: float
    total_ms: float
    finish_reason: str


class Model(Protocol):
    @property
    def backend_id(self) -> str: ...

    def generate(self, ids: list[int], max_new_tokens: int) -> Generation: ...

    def count(self, text: str) -> int: ...
