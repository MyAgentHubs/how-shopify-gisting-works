import pytest
from fakes.real_model import MODEL_DIR, needs_tokenizer
from prompt_support import ARGUMENTS, FOUND, LOOKUP, build, hf_messages

from gisting.prompt.messages import AssistantMessage, Message, ToolCall, ToolMessage, UserMessage
from gisting.prompt.schema import load_tool_schemas
from gisting.prompt.tokenizer import PromptTokenizer

SECOND_ARGUMENTS = {"order_number": "#1003", "email": "other@example.com"}
CONVERSATIONS: dict[str, list[Message]] = {
    "single_question": [UserMessage("What are your opening hours?")],
    "tool_call_and_response": [*LOOKUP, ToolMessage(FOUND)],
    "multi_turn": [
        UserMessage("Hi there"),
        AssistantMessage("Hello! How can I help?"),
        *LOOKUP,
        ToolMessage(FOUND),
        AssistantMessage("Order #1002 was found."),
        UserMessage("Thanks. And what about the carrier?"),
    ],
    "content_then_call": [
        UserMessage("check #1002 someone@example.com"),
        AssistantMessage("One moment.", (ToolCall("lookup_order", ARGUMENTS),)),
        ToolMessage(FOUND),
    ],
    "two_calls_two_responses": [
        UserMessage("check #1002 and #1003"),
        AssistantMessage(
            "",
            (ToolCall("lookup_order", ARGUMENTS), ToolCall("lookup_order", SECOND_ARGUMENTS)),
        ),
        ToolMessage(FOUND),
        ToolMessage('{"status": "no_match", "message": "No order matches."}'),
    ],
    "unicode_and_newlines": [
        UserMessage("\n\n  你好, 我的订单在哪里? 😀\n\ttabs  and   spaces \n")
    ],
    "error_round_trip": [
        UserMessage("order 1002"),
        AssistantMessage("calling"),
        ToolMessage('{"status": "invalid_tool_call", "message": "missing required argument"}'),
    ],
}


@needs_tokenizer
@pytest.mark.parametrize("name", list(CONVERSATIONS))
def test_ids_equal_the_reference_chat_template(name: str) -> None:
    transformers = pytest.importorskip("transformers", reason="transformers is in the model extra")
    reference = transformers.AutoTokenizer.from_pretrained(str(MODEL_DIR))
    messages = CONVERSATIONS[name]
    expected = reference.apply_chat_template(
        hf_messages(messages),
        tools=[schema.function_json() for schema in load_tool_schemas().values()],
        enable_thinking=False,
        add_generation_prompt=True,
        tokenize=True,
        return_dict=False,
    )
    assert build(PromptTokenizer.from_dir(MODEL_DIR), messages).ids == list(expected)


@needs_tokenizer
def test_lookup_conversation_ends_with_the_non_thinking_generation_prompt() -> None:
    tokenizer = PromptTokenizer.from_dir(MODEL_DIR)
    ids = build(tokenizer, [*LOOKUP, ToolMessage(FOUND)]).ids
    assert tokenizer.decode(ids).endswith("<|im_start|>assistant\n<think>\n\n</think>\n\n")
