from agent_support import QUESTION, good_call, internal_of, public_of, rig, tool_call

from gisting.prompt.messages import AssistantMessage, UserMessage


def test_the_internal_trace_records_the_messages_each_model_call_saw() -> None:
    subject = rig("Hello! How can I help with your order?")
    result = subject.run([UserMessage("hi"), AssistantMessage("Hello"), UserMessage("hi again")])
    call = internal_of(result)["model_calls"][0]
    assert call["input_messages"] == [
        {"role": "user", "content": "hi", "tool_calls": []},
        {"role": "assistant", "content": "Hello", "tool_calls": []},
        {"role": "user", "content": "hi again", "tool_calls": []},
    ]


def test_a_later_model_call_records_the_tool_traffic_that_came_before_it() -> None:
    subject = rig(tool_call(order_number="#1042"), good_call())
    result = subject.run()
    calls = internal_of(result)["model_calls"]
    assert [m["role"] for m in calls[0]["input_messages"]] == ["user"]
    assert [m["role"] for m in calls[1]["input_messages"]] == ["user", "assistant", "tool"]
    assert "invalid_arguments" in calls[1]["input_messages"][2]["content"]


def test_the_public_trace_gets_no_message_text() -> None:
    result = rig(good_call()).run()
    assert "input_messages" not in str(public_of(result))
    assert QUESTION not in str(public_of(result))
