import json
from functools import cache
from pathlib import Path
from typing import Any

from gisting.eval.case import FIRST, RAW, SECOND, Case, Verdict
from gisting.eval.data import load_grader_data
from gisting.eval.data_model import GraderData
from gisting.eval.grade import grade
from gisting.prompt.messages import AssistantMessage, Message, ToolCall, ToolMessage, UserMessage
from gisting.prompt.parse import parse_output
from gisting.shopify.jsonvalue import JsonObject
from gisting.tools.facts import OrderFacts, Shipment, tag
from gisting.tools.outcomes import Found
from gisting.tools.policy import load_policy
from gisting.tools.render import render_result

CORPUS_DIR = Path(__file__).resolve().parent / "corpus"
EMAIL = "ava.chen@example.com"
ORDER = "#1042"
QUESTION = f"Where is order {ORDER}? My email is {EMAIL}."
FIRST_QUESTIONS = {
    "order_full": f"Where is order {ORDER}? My email is {EMAIL}.",
    "order_no_email": f"Where is order {ORDER}?",
    "order_no_number": f"Where is my order? My email is {EMAIL}.",
}
SHIPPED = ("IN_TRANSIT", "OUT_FOR_DELIVERY", "DELIVERED", "DELAYED", "ATTEMPTED_DELIVERY")
BASE_SHIPMENT = {
    "transport_status": "IN_TRANSIT",
    "carrier": "Test Parcel",
    "tracking_number": "TP-5257262993",
    "estimated_delivery": "2026-10-05T10:00:00Z",
    "delivered_at": None,
    "updated_at": "2026-10-01T09:00:00Z",
}


@cache
def grader() -> GraderData:
    return load_grader_data()


def shipment_values(scenario: str) -> dict[str, str | None]:
    values = dict(BASE_SHIPMENT)
    if scenario in SHIPPED or scenario == "PARTIALLY_FULFILLED":
        values["transport_status"] = "IN_TRANSIT" if scenario == "PARTIALLY_FULFILLED" else scenario
    if scenario == "DELIVERED":
        values.update(estimated_delivery=None, delivered_at="2026-10-05T10:00:00Z")
    if scenario == "FULFILLED_NO_TRACKING":
        values = dict.fromkeys(values)
        values["transport_status"] = "FULFILLED"
    return values


def found_result(scenario: str, **overrides: str | None) -> JsonObject:
    sources = load_policy().sources
    fulfillment = scenario if scenario in ("UNFULFILLED", "PARTIALLY_FULFILLED") else "FULFILLED"
    order = {"order_number": ORDER, "canary": "GLR-5EE1F9FA", "fulfillment_status": fulfillment}
    shipments: tuple[Shipment, ...] = ()
    if scenario != "UNFULFILLED":
        values = {**shipment_values(scenario), **overrides}
        shipments = (Shipment(tag(values, sources)),)
    return render_result(Found(OrderFacts(tag(order, sources), shipments)))


def tool_content(spec: str | dict[str, Any]) -> str:
    if isinstance(spec, str):
        return json.dumps({"status": spec})
    if "found" in spec:
        overrides = {key: value for key, value in spec.items() if key != "found"}
        return json.dumps(found_result(spec["found"], **overrides))
    if "raw_text" in spec:
        return str(spec["raw_text"])
    if "missing" in spec:
        return json.dumps({"status": "needs_customer_input", "missing": spec["missing"]})
    return json.dumps(spec["raw"])


def message_of(item: dict[str, Any]) -> Message:
    if item["role"] == "user":
        return UserMessage(item["content"])
    if item["role"] == "tool":
        return ToolMessage(item["content"])
    calls = tuple(ToolCall(c["name"], c["arguments"]) for c in item.get("tool_calls", ()))
    return AssistantMessage(item["content"], calls)


def build_case(spec: dict[str, Any]) -> Case:
    if "messages" in spec:
        prior = tuple(message_of(item) for item in spec["messages"])
        return Case(
            spec["category"],
            spec.get("kind", FIRST),
            spec.get("scenario"),
            spec.get("order_number"),
            spec.get("email"),
            prior,
        )
    category, kind = spec["category"], spec.get("kind", FIRST)
    users = spec.get("user", QUESTION if kind == SECOND else FIRST_QUESTIONS.get(category, ""))
    messages: list[Message] = [
        UserMessage(text) for text in ([users] if isinstance(users, str) else users)
    ]
    order = ORDER if category in ("order_full", "order_no_email") or kind == SECOND else None
    email = EMAIL if category == "order_full" or kind == SECOND else None
    if kind == SECOND:
        call = ToolCall("lookup_order", {"order_number": ORDER, "email": EMAIL})
        messages += [AssistantMessage("", (call,)), ToolMessage(tool_content(spec["result"]))]
        for result in spec.get("policy", ()):
            search = ToolCall("search_policy", {"query": "returns"})
            messages += [AssistantMessage("", (search,)), ToolMessage(json.dumps(result))]
    return Case(category, kind, spec.get("scenario"), order, email, tuple(messages))


def verdict_of(spec: dict[str, Any], output: str | None = None, layer: str = RAW) -> Verdict:
    text = spec["output"] if output is None else output
    return grade(build_case(spec), parse_output(text), grader(), layer)


def call_text(order: object = ORDER, email: object = EMAIL, name: str = "lookup_order") -> str:
    body = {"name": name, "arguments": {"order_number": order, "email": email}}
    return f"<tool_call>\n{json.dumps(body)}\n</tool_call>"


def load_corpus(name: str) -> list[dict[str, Any]]:
    return json.loads((CORPUS_DIR / name).read_text(encoding="utf-8"))
