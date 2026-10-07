import threading
import time
from dataclasses import dataclass, field

from fakes.shopify import FakeOrder, FakeTransport
from serve_support import traces

from gisting.agent.state import TurnResult
from gisting.prompt.messages import Message
from gisting.serve.config import LIMITS
from gisting.serve.contract import GenerateRequest
from gisting.serve.failures import FailureLimits, FailureStore
from gisting.serve.gate import Gate, GateLimits
from gisting.serve.scope import TurnScope
from gisting.serve.service import Served, Service
from gisting.serve.store import SessionStore, StoreLimits
from gisting.shopify.client import AdminClient
from gisting.shopify.demo_email import demo_email
from gisting.shopify.target import BATCH_TAG
from gisting.tools.cache import InMemoryOrderCache
from gisting.tools.factory import build_lookup
from gisting.tools.policy import load_policy

POLICY = load_policy()
SECRET = "metering-secret-0123456789"
NUMBER = 1042
IP = "ip-digest-attacker"
CORRECT = "correct"
Plan = dict[tuple[str, str], list[str]]


def correct_email() -> str:
    return demo_email(SECRET, f"#{NUMBER}")


def wrong(label: str) -> str:
    return f"{label}@orders.example.com"


def demo_order() -> FakeOrder:
    order = FakeOrder(NUMBER, email=correct_email())
    order.tags = [BATCH_TAG, *POLICY.required_tags]
    return order


@dataclass
class World:
    plan: Plan = field(default_factory=lambda: {})
    log: list[tuple[str, str]] = field(default_factory=lambda: [])
    fake: FakeTransport = field(default_factory=lambda: FakeTransport([demo_order()]))
    cache: InMemoryOrderCache = field(default_factory=lambda: InMemoryOrderCache(60))

    def __call__(
        self,
        mode: str,
        session_id: str,
        history: list[Message],
        scope: TurnScope,
    ) -> TurnResult:
        client = AdminClient(self.fake, sleep=lambda _seconds: None)
        tool = build_lookup(client, self.cache, scope.failures, POLICY, SECRET)
        message = history[-1].content
        for email in self.plan.get((mode, message), []):
            supplied = correct_email() if email == CORRECT else email
            response = tool.call({"order_number": str(NUMBER), "email": supplied}, session_id)
            self.log.append((mode, str(response.result["status"])))
        return TurnResult("ok", None, traces())

    def statuses(self, mode: str) -> list[str]:
        return [status for seen, status in self.log if seen == mode]


def service_for(world: World, session: int = 5, ip: int = 20) -> Service:
    store = SessionStore(StoreLimits.from_limits(LIMITS), time.monotonic)
    gate = Gate(GateLimits(2, 20.0, 5))
    ready = threading.Event()
    ready.set()
    failures = FailureStore(FailureLimits(session, ip, 86400.0, 10000), time.monotonic)
    return Service(world, store, failures, gate, ready, 5)


def serve_once(service: Service, session: str, message: str, mode: str, ip: str = IP) -> None:
    request = GenerateRequest(session, message, "gist" if mode == "gist" else "full")
    assert isinstance(service.handle(request, ip).result, Served)
