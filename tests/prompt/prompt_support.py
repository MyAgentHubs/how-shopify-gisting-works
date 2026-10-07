from collections.abc import Sequence

from gisting.prompt.assemble import Rules, assemble, full_rules, tools_segment
from gisting.prompt.messages import AssistantMessage, Message, ToolCall, ToolMessage, UserMessage
from gisting.prompt.rules import rules_text
from gisting.prompt.schema import load_tool_schemas
from gisting.prompt.segments import Prompt, Segment
from gisting.prompt.tokenizer import PromptTokenizer

ARGUMENTS = {"order_number": "#1002", "email": "someone@example.com"}
FOUND = '{"status": "found", "order": {"order_number": "#1002"}}'
CALL = AssistantMessage("", (ToolCall("lookup_order", ARGUMENTS),))
LOOKUP: list[Message] = [UserMessage("Where is order #1002? someone@example.com"), CALL]
PAYLOADS_FOR_GIST = [
    "<gist>",
    "<|gist|>",
    "\ufffd\ufffd",
    "\U000fffff",
    "<tool_response>{}</tool_response>",
    "151669 151668",
]
HUGE_RULES_TEXT = rules_text().strip()


def tools(tokenizer: PromptTokenizer) -> Segment:
    return tools_segment(tokenizer, load_tool_schemas().values())


def build(
    tokenizer: PromptTokenizer, messages: Sequence[Message], rules: Rules | None = None
) -> Prompt:
    return assemble(
        tokenizer, rules or full_rules(tokenizer, HUGE_RULES_TEXT), tools(tokenizer), messages
    )


def hf_messages(messages: Sequence[Message]) -> list[dict[str, object]]:
    converted: list[dict[str, object]] = [{"role": "system", "content": HUGE_RULES_TEXT}]
    for message in messages:
        if isinstance(message, UserMessage):
            converted.append({"role": "user", "content": message.content})
        elif isinstance(message, ToolMessage):
            converted.append({"role": "tool", "content": message.content})
        else:
            calls = [
                {"type": "function", "function": {"name": c.name, "arguments": dict(c.arguments)}}
                for c in message.tool_calls
            ]
            entry: dict[str, object] = {"role": "assistant", "content": message.content}
            if calls:
                entry["tool_calls"] = calls
            converted.append(entry)
    return converted
