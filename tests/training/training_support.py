import json

from gisting.eval.case import FIRST, SECOND
from gisting.prompt.messages import AssistantMessage, Message, ToolCall, ToolMessage, UserMessage
from gisting.training.samples import Sample

EMAIL = "ava.chen@example.com"
RESULT = {
    "status": "found",
    "order": {
        "order_number": {"value": "#1042", "source": "shopify"},
        "fulfillment_status": {"value": "FULFILLED", "source": "shopify"},
        "shipments": [
            {
                "transport_status": {"value": "IN_TRANSIT", "source": "simulated"},
                "carrier": {"value": "Test Parcel", "source": "shopify"},
                "tracking_number": {"value": "TP-5257262993", "source": "shopify"},
                "estimated_delivery": {"value": "2026-10-05T10:00:00Z", "source": "simulated"},
            }
        ],
    },
}


def first_sample(category: str, text: str, number: str | None = None) -> Sample:
    email = EMAIL if category == "order_full" else None
    messages: tuple[Message, ...] = (UserMessage(text),)
    return Sample(
        f"s-{category}-{text}", "dev", category, "fam", FIRST, None, number, email, messages
    )


def second_sample(
    category: str = "found", scenario: str | None = "IN_TRANSIT", result: object = RESULT
) -> Sample:
    call = AssistantMessage(
        "", (ToolCall("lookup_order", {"order_number": "#1042", "email": EMAIL}),)
    )
    messages: tuple[Message, ...] = (
        UserMessage(f"Where is order #1042? Email {EMAIL}"),
        call,
        ToolMessage(json.dumps(result)),
    )
    return Sample("s-second", "dev", category, "fam", SECOND, scenario, "#1042", EMAIL, messages)
