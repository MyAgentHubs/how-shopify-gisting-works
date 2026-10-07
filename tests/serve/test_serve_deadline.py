from dataclasses import dataclass, field

import pytest
from fakes.model import FakeModel

from gisting.agent.state import ToolResponse
from gisting.model_server.interface import Model
from gisting.serve.deadline import (
    Deadline,
    DeadlineExceeded,
    DeadlineModel,
    DeadlineTool,
    DeadlineTransport,
)
from gisting.shopify.jsonvalue import JsonObject
from gisting.shopify.results import Ok, Result
from gisting.shopify.target import DEV_STORE
from gisting.shopify.transport import Request


@dataclass
class Clock:
    now: float = 0.0

    def __call__(self) -> float:
        return self.now


@dataclass
class Counting:
    inner: FakeModel
    calls: list[str] = field(default_factory=lambda: [])

    @property
    def backend_id(self) -> str:
        return self.inner.backend_id

    def generate(self, ids: list[int], max_new_tokens: int):
        self.calls.append("generate")
        return self.inner.generate(ids, max_new_tokens)

    def count(self, text: str) -> int:
        return self.inner.count(text)


def test_deadline_arithmetic() -> None:
    clock = Clock(10.0)
    deadline = Deadline(15.0, clock)
    assert deadline.remaining() == 5.0
    assert not deadline.expired()
    clock.now = 15.0
    assert deadline.expired()
    assert deadline.remaining() == 0.0
    clock.now = 99.0
    assert deadline.remaining() == 0.0


def test_check_raises_only_after_expiry() -> None:
    clock = Clock()
    deadline = Deadline(1.0, clock)
    deadline.check()
    clock.now = 1.0
    with pytest.raises(DeadlineExceeded):
        deadline.check()


def test_wrapped_model_delegates_before_the_deadline() -> None:
    inner = Counting(FakeModel(["one", "two"]))
    wrapped: Model = DeadlineModel(inner, Deadline(5.0, Clock()))
    assert wrapped.backend_id == "fake-model"
    assert wrapped.generate([1, 2], 8).text == "one"
    assert wrapped.count("a b c") == 3
    assert inner.calls == ["generate"]


def test_wrapped_model_refuses_every_call_after_the_deadline() -> None:
    clock = Clock()
    inner = Counting(FakeModel(["one", "two"]))
    wrapped = DeadlineModel(inner, Deadline(5.0, clock))
    wrapped.generate([1], 8)
    clock.now = 5.0
    with pytest.raises(DeadlineExceeded):
        wrapped.generate([1], 8)
    assert inner.calls == ["generate"]
    assert inner.inner.outputs == ["two"]


def test_clamp_limits_a_wish_to_what_is_left_and_refuses_when_nothing_is() -> None:
    clock = Clock(10.0)
    deadline = Deadline(15.0, clock)
    assert deadline.clamp(2.0) == 2.0
    assert deadline.clamp(60.0) == 5.0
    clock.now = 15.0
    with pytest.raises(DeadlineExceeded):
        deadline.clamp(0.1)
    clock.now = 99.0
    with pytest.raises(DeadlineExceeded):
        deadline.clamp(0.1)


class Recording:
    store = DEV_STORE

    def __init__(self) -> None:
        self.calls: list[Request] = []

    def execute(self, request: Request) -> Result:
        self.calls.append(request)
        return Ok({})


REQUEST = Request("order_state", "query { x }", {})


def test_the_transport_runs_until_the_deadline_and_never_after() -> None:
    clock = Clock()
    inner = Recording()
    transport = DeadlineTransport(inner, Deadline(5.0, clock))
    assert transport.store == DEV_STORE
    assert transport.execute(REQUEST) == Ok({})
    clock.now = 5.0
    with pytest.raises(DeadlineExceeded):
        transport.execute(REQUEST)
    assert inner.calls == [REQUEST]


class Tool:
    def __init__(self) -> None:
        self.calls = 0

    def call(self, arguments: JsonObject, session_id: str) -> ToolResponse:
        self.calls += 1
        raise AssertionError((arguments, session_id))


def test_a_tool_is_not_called_after_the_deadline() -> None:
    inner = Tool()
    tool = DeadlineTool(inner, Deadline(1.0, Clock(2.0)))
    with pytest.raises(DeadlineExceeded):
        tool.call({}, "session-1")
    assert inner.calls == 0
