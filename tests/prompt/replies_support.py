from typing import Any


def field(value: str | None, source: str = "shopify") -> dict[str, Any]:
    return {"value": value, "source": source}


def shipment(
    status: str,
    tracking: str | None = "TP-1",
    estimated: str | None = "2026-10-05T10:00:00Z",
    delivered: str | None = None,
) -> dict[str, Any]:
    return {
        "transport_status": field(status),
        "carrier": field("Test Parcel" if tracking else None),
        "tracking_number": field(tracking),
        "estimated_delivery": field(estimated),
        "delivered_at": field(delivered),
        "updated_at": field("2026-10-01T09:00:00Z"),
    }


def found(fulfillment: str, *shipments: dict[str, Any]) -> dict[str, Any]:
    order = {"fulfillment_status": field(fulfillment), "shipments": list(shipments)}
    return {"status": "found", "order": order}


def detailed(
    status: str,
    carrier: str | None = "Test Parcel",
    tracking: str | None = "TP-1",
    estimated: str | None = "2026-10-05T10:00:00Z",
    delivered: str | None = None,
) -> dict[str, Any]:
    return {
        "transport_status": field(status),
        "carrier": field(carrier),
        "tracking_number": field(tracking),
        "estimated_delivery": field(estimated),
        "delivered_at": field(delivered),
        "updated_at": field("2026-10-01T09:00:00Z"),
    }
