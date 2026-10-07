import json
from collections.abc import Callable
from dataclasses import dataclass, field

from fakes.model import FakeModel
from fakes.shopify import FakeOrder, FakeTransport
from fakes.tokenizer import synthetic_prompt_tokenizer
from serve_support import FakeTurn

from gisting.agent.assemble import Loaded
from gisting.agent.state import TurnResult
from gisting.prompt.messages import Message, UserMessage
from gisting.serve.contract import Mode
from gisting.serve.deadline import Deadline
from gisting.serve.lookup_client import client_factory
from gisting.serve.runner import LookupParts, TurnRunner, make_runner
from gisting.serve.scope import TurnScope
from gisting.shopify.demo_email import demo_email
from gisting.shopify.http_wire import Clamp
from gisting.shopify.results import Result
from gisting.shopify.target import BATCH_TAG
from gisting.shopify.transport import Request, Transport
from gisting.tools.cache import InMemoryOrderCache
from gisting.tools.policy import load_policy

SECRET = "runner-test-secret-value"
SESSION = "session-4"
NUMBER = 1042
GOOD_EMAIL = demo_email(SECRET, f"#{NUMBER}")
WRONG_EMAIL = "someone.else@example.com"
GIST_COUNT = 16
READ_ATTEMPTS = 3
RETRY_SECONDS = 5.0


def no_sleep(_seconds: float) -> None:
    return None


@dataclass(frozen=True)
class Plain:
    inner: Transport

    @property
    def store(self) -> str:
        return self.inner.store

    def execute(self, request: Request) -> Result:
        return self.inner.execute(request)

    def bounded(self, clamp: Clamp) -> Transport:
        return self.inner


def lookup_parts(transport: Transport, sleep: Callable[[float], None] = no_sleep) -> LookupParts:
    factory = client_factory(Plain(transport), sleep, READ_ATTEMPTS, RETRY_SECONDS)
    return LookupParts(factory, InMemoryOrderCache(60), load_policy(), SECRET)


def clock_at(now: float) -> Deadline:
    return Deadline(now, lambda: 0.0)


def open_deadline() -> Deadline:
    return clock_at(1000.0)


def expired_deadline() -> Deadline:
    return Deadline(1.0, lambda: 2.0)


def lookup_call(email: str) -> str:
    arguments = {"order_number": f"#{NUMBER}", "email": email}
    call = json.dumps({"name": "lookup_order", "arguments": arguments})
    return f"<tool_call>\n{call}\n</tool_call>"


def greeting() -> list[Message]:
    return [UserMessage("Hello there")]


def asking(email: str) -> list[Message]:
    return [UserMessage(f"Where is order #{NUMBER}? My email is {email}")]


def demo_order() -> FakeOrder:
    order = FakeOrder(NUMBER, email=GOOD_EMAIL)
    order.tags = [BATCH_TAG, *load_policy().required_tags]
    return order


@dataclass
class Rig:
    gist_model: FakeModel = field(default_factory=lambda: FakeModel([], "gist-backend"))
    full_model: FakeModel = field(default_factory=lambda: FakeModel([], "full-backend"))
    fake: FakeTransport = field(default_factory=lambda: FakeTransport([demo_order()]))
    lookup: LookupParts | None = None
    runner: TurnRunner = field(init=False)

    def __post_init__(self) -> None:
        tokenizer = synthetic_prompt_tokenizer()
        parts = self.lookup or lookup_parts(self.fake)
        gist = Loaded(self.gist_model, tokenizer, GIST_COUNT, "run-1")
        self.runner = make_runner(gist, Loaded(self.full_model, tokenizer), parts)


@dataclass
class RigTurn(FakeTurn):
    rig: Rig = field(default_factory=Rig)
    then: Callable[[], None] | None = None

    def __call__(
        self,
        mode: str,
        session_id: str,
        history: list[Message],
        scope: TurnScope,
    ) -> TurnResult:
        kind: Mode = "gist" if mode == "gist" else "full"
        result = self.rig.runner(kind, session_id, history, scope)
        if self.then is not None:
            self.then()
        return result
