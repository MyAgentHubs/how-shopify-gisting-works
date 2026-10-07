import json
from dataclasses import replace
from typing import Any

import pytest
from agent_support import QUESTION, SESSION, rig, tool_call

from gisting.agent.answers import handoff_reason, parse_answer_rules
from gisting.agent.policy import load_agent_policy
from gisting.prompt.files import PROMPTS_DIR
from gisting.prompt.messages import AssistantMessage, Message, ToolCall, ToolMessage, UserMessage
from gisting.prompt.phrases import load_phrases
from gisting.prompt.replies import fixed_reply
from gisting.shopify.jsonvalue import MalformedResponse

RULES = load_agent_policy().answers
PHRASES = load_phrases()
OFFER = PHRASES.handoff_offer
LOOKUP_CALL = AssistantMessage("", (ToolCall("lookup_order", {"order_number": "#1042"}),))


def leaf(value: str | None) -> dict[str, Any]:
    return {"value": value, "source": "shopify"}


def parcel(status: str, tracking: str | None = "TP-1") -> dict[str, Any]:
    return {
        "transport_status": leaf(status),
        "carrier": leaf("Test Parcel" if tracking else None),
        "tracking_number": leaf(tracking),
        "estimated_delivery": leaf("2026-10-05T10:00:00Z"),
        "delivered_at": leaf(None),
        "updated_at": leaf("2026-10-01T09:00:00Z"),
    }


def found(fulfillment: str, *parcels: dict[str, Any]) -> dict[str, Any]:
    order = {"fulfillment_status": leaf(fulfillment), "shipments": list(parcels)}
    return {"status": "found", "order": order}


def after_result(result: dict[str, Any], reply: str = "yes") -> list[Message]:
    return [
        UserMessage(QUESTION),
        LOOKUP_CALL,
        ToolMessage(json.dumps(result)),
        AssistantMessage(OFFER),
        UserMessage(reply),
    ]


def after_text(result: dict[str, Any], reply: str = "yes") -> list[Message]:
    text = fixed_reply(PHRASES, result)
    assert OFFER in text
    return [UserMessage(QUESTION), AssistantMessage(text), UserMessage(reply)]


CASES = [
    ("single_attempted", found("FULFILLED", parcel("ATTEMPTED_DELIVERY")), "attempted_delivery"),
    (
        "attempted_second",
        found("FULFILLED", parcel("IN_TRANSIT"), parcel("ATTEMPTED_DELIVERY")),
        "attempted_delivery",
    ),
    (
        "attempted_third",
        found("FULFILLED", parcel("DELIVERED"), parcel("IN_TRANSIT"), parcel("ATTEMPTED_DELIVERY")),
        "attempted_delivery",
    ),
    ("delayed_second", found("FULFILLED", parcel("IN_TRANSIT"), parcel("DELAYED")), "delayed"),
    (
        "attempted_beats_delayed",
        found("FULFILLED", parcel("DELAYED"), parcel("ATTEMPTED_DELIVERY")),
        "attempted_delivery",
    ),
    ("single_no_tracking", found("FULFILLED", parcel("FULFILLED", None)), "no_tracking"),
    ("failure_locked", {"status": "locked"}, "locked"),
    ("failure_unavailable", {"status": "unavailable"}, "unavailable"),
]


@pytest.mark.parametrize(("name", "result", "reason"), CASES, ids=[c[0] for c in CASES])
def test_the_reason_comes_from_every_parcel_of_the_lookup_result_in_the_history(
    name: str, result: dict[str, Any], reason: str
) -> None:
    assert name
    assert handoff_reason(RULES, after_result(result), requested=False) == reason
    subject = rig(tool_call("handoff_to_human"))
    subject.run(after_result(result))
    assert subject.handoff.calls == [({"reason": reason}, SESSION)]


@pytest.mark.parametrize(
    "result",
    [
        found("FULFILLED", parcel("IN_TRANSIT"), parcel("OUT_FOR_DELIVERY")),
        found("FULFILLED", parcel("DELIVERED")),
        found("UNFULFILLED"),
        found("FULFILLED", *[parcel("IN_TRANSIT")] * 4),
        {"status": "no_match"},
    ],
)
def test_a_result_with_nothing_to_hand_over_for_gets_customer_request(
    result: dict[str, Any],
) -> None:
    assert handoff_reason(RULES, after_result(result), requested=False) == "customer_request"


def test_the_latest_lookup_result_decides() -> None:
    history: list[Message] = [
        *after_result(found("FULFILLED", parcel("DELAYED")))[:-1],
        UserMessage("what about 1043"),
        LOOKUP_CALL,
        ToolMessage(json.dumps(found("FULFILLED", parcel("ATTEMPTED_DELIVERY")))),
        AssistantMessage(OFFER),
        UserMessage("yes"),
    ]
    assert handoff_reason(RULES, history, requested=False) == "attempted_delivery"


def test_a_customer_who_asks_for_a_human_gets_customer_request_whatever_the_result_said() -> None:
    history = after_result(found("FULFILLED", parcel("DELAYED")), "I want to talk to a human")
    assert handoff_reason(RULES, history, requested=True) == "customer_request"


TEXT_CASES = [
    case for case in CASES if case[1].get("status") == "found" and case[0] != "single_no_tracking"
]


@pytest.mark.parametrize(("name", "result", "reason"), TEXT_CASES, ids=[c[0] for c in TEXT_CASES])
def test_a_history_with_only_the_rendered_reply_gives_the_same_reason(
    name: str, result: dict[str, Any], reason: str
) -> None:
    del name
    assert handoff_reason(RULES, after_text(result), requested=False) == reason


def test_the_priority_between_reasons_is_data() -> None:
    result = found("FULFILLED", parcel("DELAYED"), parcel("ATTEMPTED_DELIVERY"))
    assert RULES.priority.index("ATTEMPTED_DELIVERY") < RULES.priority.index("DELAYED")
    flipped = replace(
        RULES, priority=("DELAYED", "ATTEMPTED_DELIVERY", "FULFILLED", "unavailable", "locked")
    )
    assert handoff_reason(flipped, after_result(result), requested=False) == "delayed"


def test_the_priority_lists_every_status_which_has_a_reason() -> None:
    assert set(RULES.priority) == set(RULES.reasons)


@pytest.mark.parametrize(
    "priority", [["DELAYED"], ["DELAYED", "DELAYED", "FULFILLED", "locked", "unavailable"], []]
)
def test_a_priority_list_that_does_not_match_the_reasons_is_refused(priority: list[str]) -> None:
    document = json.loads((PROMPTS_DIR / "agent_policy.json").read_text(encoding="utf-8"))
    document["answers"]["handoff_reasons"]["priority"] = priority
    with pytest.raises(MalformedResponse):
        parse_answer_rules(document["answers"], PHRASES)
