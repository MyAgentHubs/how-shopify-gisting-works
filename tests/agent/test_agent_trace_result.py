import json

from agent_support import CANARY, good_call, internal_of, public_of, rig, tool_call
from test_agent_handoff import handoff_call

from gisting.prompt.messages import UserMessage


def test_the_internal_trace_records_the_result_the_tool_returned() -> None:
    subject = rig(good_call())
    result = subject.run()
    call = internal_of(result)["tool_calls"][0]
    assert isinstance(call["result"], str)
    wire = json.loads(call["result"])
    assert wire["status"] == "found"
    assert wire["order"]["canary"]["value"] == CANARY


def test_a_call_that_never_ran_has_no_result() -> None:
    subject = rig(tool_call(order_number="#1042"), tool_call(order_number="#1042"))
    calls = internal_of(subject.run())["tool_calls"]
    assert calls
    assert all(call["result"] is None for call in calls)


def test_a_reused_call_carries_the_result_of_the_first() -> None:
    subject = rig(handoff_call() * 2, "never used")
    calls = internal_of(subject.run([UserMessage("I want to talk to a human")]))["tool_calls"]
    assert isinstance(calls[0]["result"], str)
    assert calls[1]["result"] == calls[0]["result"]


def test_the_public_trace_still_carries_no_result() -> None:
    result = rig(good_call()).run()
    assert [set(tool) for tool in public_of(result)["tools"]] == [
        {"tool", "order_number", "outcome"}
    ]
    assert CANARY not in json.dumps(public_of(result))
