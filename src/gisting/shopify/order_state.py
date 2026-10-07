from dataclasses import dataclass

from gisting.shopify.jsonvalue import (
    JsonObject,
    collect_gids,
    connection_nodes,
    object_items,
    optional_str,
    required_bool,
    required_int,
    required_list,
    required_object,
    required_str,
    string_list,
)


@dataclass(frozen=True)
class Tracking:
    company: str | None
    number: str | None
    url: str | None


@dataclass(frozen=True)
class EventState:
    status: str
    happened_at: str | None


@dataclass(frozen=True)
class FulfillmentState:
    id: str
    status: str
    display_status: str | None
    quantity: int
    estimated_delivery_at: str | None
    delivered_at: str | None
    tracking: tuple[Tracking, ...]
    events: tuple[EventState, ...]


@dataclass(frozen=True)
class FulfillmentOrderLine:
    id: str
    total: int
    remaining: int


@dataclass(frozen=True)
class FulfillmentOrderState:
    id: str
    status: str
    lines: tuple[FulfillmentOrderLine, ...]


@dataclass(frozen=True)
class OrderState:
    id: str
    name: str
    test: bool
    tags: tuple[str, ...]
    note: str | None
    email: str | None
    status: str
    quantity: int
    fulfillments: tuple[FulfillmentState, ...]
    fulfillment_orders: tuple[FulfillmentOrderState, ...]
    gids: frozenset[str]


def parse_tracking(node: JsonObject) -> Tracking:
    return Tracking(
        optional_str(node, "company"), optional_str(node, "number"), optional_str(node, "url")
    )


def parse_fulfillment(node: JsonObject) -> FulfillmentState:
    events = connection_nodes(node, "events")
    return FulfillmentState(
        id=required_str(node, "id"),
        status=required_str(node, "status"),
        display_status=optional_str(node, "displayStatus"),
        quantity=required_int(node, "totalQuantity"),
        estimated_delivery_at=optional_str(node, "estimatedDeliveryAt"),
        delivered_at=optional_str(node, "deliveredAt"),
        tracking=tuple(
            parse_tracking(item)
            for item in object_items(required_list(node, "trackingInfo"), "trackingInfo")
        ),
        events=tuple(
            EventState(required_str(event, "status"), optional_str(event, "happenedAt"))
            for event in events
        ),
    )


def parse_fulfillment_order(node: JsonObject) -> FulfillmentOrderState:
    lines = tuple(
        FulfillmentOrderLine(
            required_str(line, "id"),
            required_int(line, "totalQuantity"),
            required_int(line, "remainingQuantity"),
        )
        for line in connection_nodes(node, "lineItems")
    )
    return FulfillmentOrderState(required_str(node, "id"), required_str(node, "status"), lines)


def parse_order(node: JsonObject) -> OrderState:
    fulfillments = object_items(required_list(node, "fulfillments"), "fulfillments")
    return OrderState(
        id=required_str(node, "id"),
        name=required_str(node, "name"),
        test=required_bool(node, "test"),
        tags=string_list(node, "tags"),
        note=optional_str(node, "note"),
        email=optional_str(node, "email"),
        status=required_str(node, "displayFulfillmentStatus"),
        quantity=sum(
            required_int(line, "quantity") for line in connection_nodes(node, "lineItems")
        ),
        fulfillments=tuple(parse_fulfillment(item) for item in fulfillments),
        fulfillment_orders=tuple(
            parse_fulfillment_order(item) for item in connection_nodes(node, "fulfillmentOrders")
        ),
        gids=frozenset(collect_gids(node)),
    )


def shop_is_dev_store(data: JsonObject, domain: str) -> bool:
    shop = required_object(data, "shop")
    plan = required_object(shop, "plan")
    return (
        required_str(shop, "myshopifyDomain") == domain and plan.get("partnerDevelopment") is True
    )
