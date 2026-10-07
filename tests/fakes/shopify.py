from dataclasses import dataclass, field

from gisting.shopify.jsonvalue import Json, JsonObject
from gisting.shopify.results import Ok, Result
from gisting.shopify.target import BATCH_TAG, DEV_STORE
from gisting.shopify.transport import Request

MUTATIONS = frozenset({
    "order_update",
    "tags_add",
    "fulfillment_create",
    "fulfillment_event_create",
})


@dataclass
class FakeFulfillment:
    id: str
    quantity: int
    tracking: list[JsonObject]
    events: list[JsonObject] = field(default_factory=lambda: [])
    estimated_delivery_at: str | None = None
    delivered_at: str | None = None
    display_status: str = "FULFILLED"
    update_eta: bool = True


@dataclass
class FakeOrder:
    number: int
    quantity: int = 1
    test: bool = True
    tags: list[str] = field(default_factory=lambda: [BATCH_TAG])
    note: str | None = "seed note"
    email: str | None = None
    email_write: str = "store"
    remaining: int = 0
    fulfillments: list[FakeFulfillment] = field(default_factory=lambda: [])

    def __post_init__(self) -> None:
        self.remaining = self.quantity

    @property
    def name(self) -> str:
        return f"#{self.number}"

    @property
    def gid(self) -> str:
        return f"gid://shopify/Order/{self.number}"

    @property
    def fulfillment_order_gid(self) -> str:
        return f"gid://shopify/FulfillmentOrder/{self.number}"

    @property
    def fulfillment_order_line_gid(self) -> str:
        return f"gid://shopify/FulfillmentOrderLineItem/{self.number}"

    @property
    def status(self) -> str:
        if self.remaining == self.quantity:
            return "UNFULFILLED"
        return "FULFILLED" if self.remaining == 0 else "PARTIALLY_FULFILLED"


@dataclass
class Fault:
    result: Result
    applied: bool
    skip: int = 0


def user_error(message: str) -> Result:
    return Ok({"payload": {"userErrors": [{"field": None, "message": message}]}})


def obj(value: Json) -> JsonObject:
    assert isinstance(value, dict)
    return value


def items(value: Json) -> list[Json]:
    assert isinstance(value, list)
    return value


class FakeTransport:
    def __init__(
        self,
        orders: list[FakeOrder],
        store: str = DEV_STORE,
        shop_domain: str = DEV_STORE,
    ) -> None:
        self.store = store
        self.shop_domain = shop_domain
        self.orders = {order.name: order for order in orders}
        self.calls: list[Request] = []
        self.faults: dict[str, list[Fault]] = {}
        self._counter = 0

    @property
    def writes(self) -> list[Request]:
        return [call for call in self.calls if call.name in MUTATIONS]

    def fail(self, name: str, result: Result, applied: bool = False, skip: int = 0) -> None:
        self.faults.setdefault(name, []).append(Fault(result, applied, skip))

    def execute(self, request: Request) -> Result:
        self.calls.append(request)
        queue = self.faults.get(request.name)
        if queue and queue[0].skip:
            queue[0].skip -= 1
        elif queue:
            fault = queue.pop(0)
            if fault.applied:
                self._dispatch(request)
            return fault.result
        return self._dispatch(request)

    def _dispatch(self, request: Request) -> Result:
        handlers = {
            "order_state": self._order_state,
            "order_update": self._order_update,
            "tags_add": self._tags_add,
            "fulfillment_create": self._fulfillment_create,
            "fulfillment_event_create": self._event_create,
        }
        return handlers[request.name](request.variables)

    def _by_gid(self, gid: Json) -> FakeOrder | None:
        return next((order for order in self.orders.values() if order.gid == gid), None)

    def _next_id(self, kind: str) -> str:
        self._counter += 1
        return f"gid://shopify/{kind}/{self._counter}"

    def _order_state(self, variables: JsonObject) -> Result:
        query = variables["query"]
        assert isinstance(query, str)
        found = [order for name, order in self.orders.items() if query == f"name:{name}"]
        nodes: list[Json] = [self._order_json(order) for order in found]
        shop: JsonObject = {
            "myshopifyDomain": self.shop_domain,
            "plan": {"partnerDevelopment": True},
        }
        return Ok({"shop": shop, "orders": {"nodes": nodes}})

    def _order_json(self, order: FakeOrder) -> JsonObject:
        line: JsonObject = {
            "id": f"gid://shopify/LineItem/{order.number}",
            "quantity": order.quantity,
        }
        fulfillment_line: JsonObject = {
            "id": order.fulfillment_order_line_gid,
            "totalQuantity": order.quantity,
            "remainingQuantity": order.remaining,
        }
        fulfillment_order: JsonObject = {
            "id": order.fulfillment_order_gid,
            "status": "CLOSED" if order.remaining == 0 else "OPEN",
            "lineItems": {"nodes": [fulfillment_line]},
        }
        tags: list[Json] = list(order.tags)
        return {
            "id": order.gid,
            "name": order.name,
            "test": order.test,
            "tags": tags,
            "note": order.note,
            "email": order.email,
            "displayFulfillmentStatus": order.status,
            "lineItems": {"nodes": [line]},
            "fulfillments": [self._fulfillment_json(item) for item in order.fulfillments],
            "fulfillmentOrders": {"nodes": [fulfillment_order]},
        }

    def _fulfillment_json(self, fulfillment: FakeFulfillment) -> JsonObject:
        tracking: list[Json] = list(fulfillment.tracking)
        events: list[Json] = list(fulfillment.events)
        return {
            "id": fulfillment.id,
            "status": "SUCCESS",
            "displayStatus": fulfillment.display_status,
            "estimatedDeliveryAt": fulfillment.estimated_delivery_at,
            "deliveredAt": fulfillment.delivered_at,
            "totalQuantity": fulfillment.quantity,
            "trackingInfo": tracking,
            "events": {"nodes": events},
        }

    def _order_update(self, variables: JsonObject) -> Result:
        payload = obj(variables["input"])
        order = self._by_gid(payload["id"])
        assert order is not None
        note = payload.get("note")
        order.note = note if isinstance(note, str) else order.note
        email = payload.get("email")
        if order.email_write == "store" and isinstance(email, str):
            order.email = email
        elif order.email_write == "alter":
            order.email = "other@orders.example.com"
        return Ok({"orderUpdate": {"order": {"id": order.gid}, "userErrors": []}})

    def _tags_add(self, variables: JsonObject) -> Result:
        order = self._by_gid(variables["id"])
        assert order is not None
        for tag in items(variables["tags"]):
            assert isinstance(tag, str)
            if tag not in order.tags:
                order.tags.append(tag)
        return Ok({"tagsAdd": {"node": {"id": order.gid}, "userErrors": []}})

    def _fulfillment_create(self, variables: JsonObject) -> Result:
        request = obj(variables["fulfillment"])
        group = obj(items(request["lineItemsByFulfillmentOrder"])[0])
        order = next(
            o
            for o in self.orders.values()
            if o.fulfillment_order_gid == group["fulfillmentOrderId"]
        )
        line = obj(items(group["fulfillmentOrderLineItems"])[0])
        quantity = line["quantity"]
        assert isinstance(quantity, int)
        if quantity > order.remaining:
            return user_error("quantity exceeds remaining")
        order.remaining -= quantity
        tracking_input = request.get("trackingInfo")
        tracking: list[JsonObject] = [obj(tracking_input)] if tracking_input else []
        fulfillment = FakeFulfillment(self._next_id("Fulfillment"), quantity, tracking)
        order.fulfillments.append(fulfillment)
        return Ok({
            "fulfillmentCreate": {
                "fulfillment": {"id": fulfillment.id, "status": "SUCCESS"},
                "userErrors": [],
            }
        })

    def _event_create(self, variables: JsonObject) -> Result:
        event = obj(variables["fulfillmentEvent"])
        fulfillment = next(
            f
            for order in self.orders.values()
            for f in order.fulfillments
            if f.id == event["fulfillmentId"]
        )
        status = event["status"]
        assert isinstance(status, str)
        stored: JsonObject = {
            "id": self._next_id("FulfillmentEvent"),
            "status": status,
            "happenedAt": event.get("happenedAt"),
        }
        fulfillment.events.append(stored)
        fulfillment.display_status = status
        eta = event.get("estimatedDeliveryAt")
        if fulfillment.update_eta:
            fulfillment.estimated_delivery_at = eta if isinstance(eta, str) else None
        if status == "DELIVERED":
            happened = event.get("happenedAt")
            fulfillment.delivered_at = happened if isinstance(happened, str) else None
        return Ok({"fulfillmentEventCreate": {"fulfillmentEvent": stored, "userErrors": []}})
