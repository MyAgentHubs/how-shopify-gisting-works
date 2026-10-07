from collections.abc import Callable
from dataclasses import dataclass

from gisting.agent.state import ToolRunner
from gisting.model_server.interface import Generation, Model
from gisting.shopify.jsonvalue import JsonObject
from gisting.shopify.results import Result
from gisting.shopify.transport import Request, Transport
from gisting.tools.lookup_order import ToolResponse


class DeadlineExceeded(Exception):
    pass


@dataclass(frozen=True)
class Deadline:
    expires_at: float
    clock: Callable[[], float]

    def remaining(self) -> float:
        return max(0.0, self.expires_at - self.clock())

    def expired(self) -> bool:
        return self.clock() >= self.expires_at

    def check(self) -> None:
        if self.expired():
            raise DeadlineExceeded

    def clamp(self, wanted: float) -> float:
        left = self.expires_at - self.clock()
        if left <= 0:
            raise DeadlineExceeded
        return min(wanted, left)


@dataclass(frozen=True)
class DeadlineModel:
    inner: Model
    deadline: Deadline

    @property
    def backend_id(self) -> str:
        return self.inner.backend_id

    def generate(self, ids: list[int], max_new_tokens: int) -> Generation:
        self.deadline.check()
        return self.inner.generate(ids, max_new_tokens)

    def count(self, text: str) -> int:
        return self.inner.count(text)


@dataclass(frozen=True)
class DeadlineTransport:
    inner: Transport
    deadline: Deadline

    @property
    def store(self) -> str:
        return self.inner.store

    def execute(self, request: Request) -> Result:
        self.deadline.check()
        return self.inner.execute(request)


@dataclass(frozen=True)
class DeadlineTool:
    inner: ToolRunner
    deadline: Deadline

    def call(self, arguments: JsonObject, session_id: str) -> ToolResponse:
        self.deadline.check()
        return self.inner.call(arguments, session_id)
