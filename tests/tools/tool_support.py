import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from fakes.shopify import FakeFulfillment, FakeOrder, FakeTransport

from gisting.shopify.client import AdminClient
from gisting.shopify.demo_email import demo_email
from gisting.shopify.jsonvalue import Json, JsonObject
from gisting.shopify.order_state import OrderState
from gisting.shopify.target import BATCH_TAG
from gisting.tools.attempts import InMemoryFailureCounter
from gisting.tools.cache import InMemoryOrderCache
from gisting.tools.lookup_order import LookupDeps, LookupOrder, ToolResponse
from gisting.tools.policy import LookupPolicy, load_policy
from gisting.tools.reads import DISCARD, LookupSink
from gisting.tools.trace import internal_json, public_json

SECRET = "unit-test-secret"
SESSION = "session-1"
FIRST_ORDER = 1001
LAST_ORDER = 1101
POLICY = load_policy()


def email_for(number: int) -> str:
    return demo_email(SECRET, f"#{number}")


def canary_for(number: int) -> str:
    return f"GLR-{number:08X}"


def shipped_order(number: int, *, email: str | None = None) -> FakeOrder:
    order = FakeOrder(
        number,
        quantity=2,
        email=email_for(number) if email is None else email,
        note=f"Test order for Gisting Lab experiments. Reference {canary_for(number)}",
    )
    order.tags = [BATCH_TAG, *POLICY.required_tags]
    order.remaining = 0
    order.fulfillments.append(
        FakeFulfillment(
            f"gid://shopify/Fulfillment/{number}",
            2,
            [{"company": "Test Parcel", "number": f"TP-{number}", "url": "https://t.example"}],
            events=[
                {"id": "e1", "status": "LABEL_PRINTED", "happenedAt": "2026-09-30T08:00:00Z"},
                {"id": "e2", "status": "IN_TRANSIT", "happenedAt": "2026-10-01T09:00:00Z"},
            ],
            estimated_delivery_at="2026-10-05T10:00:00Z",
            display_status="IN_TRANSIT",
        )
    )
    return order


def demo_orders() -> list[FakeOrder]:
    return [shipped_order(number) for number in range(FIRST_ORDER, LAST_ORDER + 1)]


class SpyCache(InMemoryOrderCache):
    def __init__(self, ttl_seconds: float = 60) -> None:
        super().__init__(ttl_seconds)
        self.gets: list[str] = []
        self.puts: list[str] = []

    def get(self, order_name: str) -> OrderState | None:
        self.gets.append(order_name)
        return super().get(order_name)

    def put(self, order_name: str, order: OrderState) -> None:
        self.puts.append(order_name)
        super().put(order_name, order)


class SpyCounter(InMemoryFailureCounter):
    def __init__(self, limit: int) -> None:
        super().__init__(limit)
        self.reads = 0

    def failures(self, session_id: str) -> int:
        self.reads += 1
        return super().failures(session_id)


@dataclass
class Harness:
    fake: FakeTransport
    cache: SpyCache = field(default_factory=SpyCache)
    attempts: SpyCounter = field(default_factory=lambda: SpyCounter(POLICY.failure_limit))
    policy: LookupPolicy = POLICY
    clock: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = lambda _seconds: None
    reads: LookupSink = DISCARD

    @property
    def deps(self) -> LookupDeps:
        client = AdminClient(self.fake, sleep=self.sleep)
        return LookupDeps(
            client, self.cache, self.attempts, self.policy, SECRET, self.clock, self.reads
        )

    @property
    def tool(self) -> LookupOrder:
        return LookupOrder(self.deps)

    def lookup(self, order_number: str, email: str, session_id: str = SESSION) -> ToolResponse:
        arguments: JsonObject = {"order_number": order_number, "email": email}
        return self.tool.call(arguments, session_id)


def harness(*orders: FakeOrder) -> Harness:
    return Harness(FakeTransport(list(orders)))


def public_wire(response: ToolResponse) -> str:
    return json.dumps(
        {"result": response.result, "trace": public_json(response.trace.public)}, sort_keys=True
    )


def everything_wire(response: ToolResponse) -> str:
    return public_wire(response) + json.dumps(
        internal_json(response.trace.internal), sort_keys=True
    )


def state_of(order: FakeOrder) -> OrderState:
    state = AdminClient(FakeTransport([order])).fetch_order(order.name)
    assert isinstance(state, OrderState)
    return state


def obj_at(source: JsonObject, name: str) -> JsonObject:
    value = source[name]
    assert isinstance(value, dict)
    return value


def tagged(source: JsonObject, name: str) -> tuple[Json, Json]:
    field_ = obj_at(source, name)
    return field_["value"], field_["source"]


def only_shipment(result: JsonObject) -> JsonObject:
    shipments = obj_at(result, "order")["shipments"]
    assert isinstance(shipments, list)
    assert len(shipments) == 1
    shipment = shipments[0]
    assert isinstance(shipment, dict)
    return shipment
