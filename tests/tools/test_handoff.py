import json
import re

import pytest

from gisting.shopify.jsonvalue import JsonObject
from gisting.tools.handoff import SPEC, HandoffToHuman
from gisting.tools.mock import InvalidMockCall, load_reference_policy, reference_for
from gisting.tools.trace import internal_json, public_json

TICKET = re.compile(r"HO-\d{8}")


def reasons() -> list[str]:
    return list(load_reference_policy(SPEC.policy_file).derived_values)


def call(reason: str = "customer_request", session: str = "session-1") -> JsonObject:
    return HandoffToHuman().call({"reason": reason}, session).result


def test_the_result_is_a_handed_off_status_with_a_ticket() -> None:
    result = call()
    assert set(result) == {"status", "ticket"}
    assert result["status"] == "handed_off"
    assert isinstance(result["ticket"], str)
    assert TICKET.fullmatch(result["ticket"])


def test_the_ticket_is_reproducible_for_a_session_and_differs_between_sessions() -> None:
    assert call(session="a") == call(session="a")
    assert call(session="a")["ticket"] != call(session="b")["ticket"]
    assert call(session="a")["ticket"] == reference_for(
        "a", load_reference_policy(SPEC.policy_file)
    )


def test_the_ticket_does_not_depend_on_the_reason() -> None:
    assert len({str(call(reason)["ticket"]) for reason in reasons()}) == 1


@pytest.mark.parametrize("reason", ["", "angry", "Customer_Request"])
def test_a_reason_outside_the_schema_enum_is_rejected(reason: str) -> None:
    with pytest.raises(InvalidMockCall):
        HandoffToHuman().call({"reason": reason}, "session-1")


@pytest.mark.parametrize("arguments", [{}, {"reason": 3}, {"reason": "delayed", "extra": "x"}])
def test_arguments_that_break_the_schema_are_rejected(arguments: JsonObject) -> None:
    with pytest.raises(InvalidMockCall):
        HandoffToHuman().call(arguments, "session-1")


def test_the_public_trace_names_the_tool_and_the_outcome_only() -> None:
    response = HandoffToHuman().call({"reason": "delayed"}, "session-9")
    public = public_json(response.trace.public)
    assert public == {"tool": "handoff_to_human", "order_number": None, "outcome": "completed"}
    wire = json.dumps(public)
    assert "session-9" not in wire
    assert "delayed" not in wire
    assert str(response.result["ticket"]) not in wire


def test_the_internal_trace_keeps_the_reason_and_the_session() -> None:
    response = HandoffToHuman().call({"reason": "delayed"}, "session-9")
    internal = internal_json(response.trace.internal)
    assert internal["tool"] == "handoff_to_human"
    assert internal["session_id"] == "session-9"
    assert internal["result_type"] == "HandedOff"
    assert internal["detail"] == "delayed"
