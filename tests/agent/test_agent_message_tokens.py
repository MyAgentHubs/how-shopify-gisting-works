from agent_support import QUESTION, good_call, internal_of, public_of, rig, tool_call

from gisting.prompt.assemble import message_segments
from gisting.prompt.messages import AssistantMessage, ToolMessage, UserMessage


def test_each_model_call_records_the_token_count_of_every_input_message() -> None:
    subject = rig("Hello! How can I help with your order?")
    history = [UserMessage("hi"), AssistantMessage("Hello"), UserMessage("hi again")]
    call = internal_of(subject.run(list(history)))["model_calls"][0]
    expected = [len(item.ids) for item in message_segments(subject.tokenizer, history)]
    assert call["message_tokens"] == expected
    assert len(call["message_tokens"]) == len(call["input_messages"])


def test_the_message_counts_plus_rules_tools_and_the_generation_prompt_make_the_total() -> None:
    subject = rig("Hello! How can I help with your order?")
    call = internal_of(subject.run([UserMessage("hi")]))["model_calls"][0]
    tokens = call["tokens"]
    fixed = tokens["rules"] + tokens["tools"]
    assert sum(call["message_tokens"]) + fixed < tokens["total"]
    assert tokens["history"] + tokens["tool_results"] > sum(call["message_tokens"])


def test_a_later_call_counts_the_tool_traffic_before_it() -> None:
    subject = rig(tool_call(order_number="#1042"), good_call())
    calls = internal_of(subject.run())["model_calls"]
    assert len(calls[0]["message_tokens"]) == 1
    assert len(calls[1]["message_tokens"]) == 3
    messages = [UserMessage(QUESTION), AssistantMessage(""), ToolMessage("{}")]
    assert len(message_segments(subject.tokenizer, messages)) == 3


def test_the_public_trace_gets_no_per_message_counts() -> None:
    result = rig(good_call()).run()
    assert "message_tokens" not in str(public_of(result))
