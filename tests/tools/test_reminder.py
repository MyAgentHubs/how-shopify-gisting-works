import json
import re

import pytest

from gisting.shopify.jsonvalue import JsonObject
from gisting.tools.mock import InvalidMockCall
from gisting.tools.reminder import SendShippingReminder
from gisting.tools.trace import internal_json, public_json

REFERENCE = re.compile(r"SR-\d{8}")


def call(order: str = "#1042", session: str = "session-1") -> JsonObject:
    return SendShippingReminder().call({"order_number": order}, session).result


def test_the_result_is_a_requested_status_with_a_reference_and_nothing_else() -> None:
    result = call()
    assert set(result) == {"status", "reference"}
    assert result["status"] == "requested"
    assert isinstance(result["reference"], str)
    assert REFERENCE.fullmatch(result["reference"])


def test_the_reference_is_reproducible_for_a_session_and_differs_between_sessions() -> None:
    assert call(session="a") == call(session="a")
    assert call(session="a")["reference"] != call(session="b")["reference"]


@pytest.mark.parametrize(
    "arguments", [{}, {"order_number": 1042}, {"order_number": "#1", "x": "y"}]
)
def test_arguments_that_break_the_schema_are_rejected(arguments: JsonObject) -> None:
    with pytest.raises(InvalidMockCall):
        SendShippingReminder().call(arguments, "session-1")


def test_the_public_trace_names_the_tool_and_the_outcome_only() -> None:
    response = SendShippingReminder().call({"order_number": "#1042"}, "session-9")
    public = public_json(response.trace.public)
    assert public == {
        "tool": "send_shipping_reminder",
        "order_number": None,
        "outcome": "completed",
    }
    wire = json.dumps(public)
    for hidden in ("session-9", "#1042", str(response.result["reference"])):
        assert hidden not in wire


def test_the_internal_trace_keeps_the_order_and_the_session() -> None:
    response = SendShippingReminder().call({"order_number": "#1042"}, "session-9")
    internal = internal_json(response.trace.internal)
    assert internal["order_number"] == "#1042"
    assert internal["session_id"] == "session-9"
    assert internal["result_type"] == "ShippingReminderSent"


def test_the_reference_prefix_is_sr_and_never_the_old_sp() -> None:
    assert call()["reference"] == call()["reference"]
    assert str(call()["reference"]).startswith("SR-")
