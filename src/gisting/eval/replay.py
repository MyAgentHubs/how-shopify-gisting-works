import json
from collections.abc import Sequence

from gisting.eval.report_tokens import as_object, model_calls
from gisting.prompt.assemble import Rules, assemble, full_rules, gist_rules, tools_segment
from gisting.prompt.messages import AssistantMessage, Message, ToolCall, ToolMessage, UserMessage
from gisting.prompt.schema import load_tool_schemas
from gisting.prompt.segments import Kind, Segment
from gisting.prompt.tokenizer import PromptTokenizer
from gisting.shopify.jsonvalue import Json, JsonObject

GIST_MODE = "gist"
SLOT_MARK = "{email_"


def message_of(item: Json) -> Message:
    node = as_object(item)
    content = str(node.get("content", ""))
    role = node.get("role")
    if role == "tool":
        return ToolMessage(content)
    if role == "assistant":
        calls = node.get("tool_calls")
        found = [as_object(call) for call in calls] if isinstance(calls, list) else []
        tools = tuple(
            ToolCall(str(c.get("name", "")), as_object(c.get("arguments"))) for c in found
        )
        return AssistantMessage(content, tools)
    return UserMessage(content)


def rules_of(tokenizer: PromptTokenizer, row: JsonObject, mode: str) -> Rules | str:
    if mode != GIST_MODE:
        return full_rules(tokenizer)
    gist = as_object(as_object(as_object(row.get("internal")).get("model")).get("gist"))
    count = gist.get("k")
    if not isinstance(count, int) or isinstance(count, bool) or count < 1:
        return "the model identity has no gist size k"
    return gist_rules(tokenizer, count)


def recorded_sizes(call: JsonObject, expected: int) -> list[int] | None:
    sizes = call.get("message_tokens")
    if not isinstance(sizes, list) or len(sizes) != expected:
        return None
    numbers = [size for size in sizes if isinstance(size, int) and not isinstance(size, bool)]
    return numbers if len(numbers) == expected else None


def replayed_sizes(segments: Sequence[Segment]) -> tuple[list[int], int]:
    chats = [item for item in segments if item.kind in (Kind.HISTORY, Kind.TOOL_RESULTS)]
    return [len(item.ids) for item in chats[:-1]], len(chats[-1].ids)


def call_problems(
    label: str, call: JsonObject, tokenizer: PromptTokenizer, rules: Rules, section: Segment
) -> list[str]:
    raw = call.get("input_messages")
    items = raw if isinstance(raw, list) else []
    messages = [message_of(item) for item in items]
    prompt = assemble(tokenizer, rules, section, messages)
    now, tail = replayed_sizes(prompt.segments)
    seen = recorded_sizes(call, len(messages))
    if seen is None:
        return [f"{label}: message_tokens do not line up with input_messages"]
    found = [
        f"{label} message {index}: recorded {size}, replay gives {again}"
        for index, (item, size, again) in enumerate(zip(items, seen, now, strict=True))
        if SLOT_MARK not in json.dumps(item) and size != again
    ]
    chat = sum(
        n for n, item in zip(seen, messages, strict=True) if not isinstance(item, ToolMessage)
    )
    fixed = prompt.stats.rules + prompt.stats.tools
    expected = {
        "rules": prompt.stats.rules,
        "tools": prompt.stats.tools,
        "history": chat + tail,
        "tool_results": sum(seen) - chat,
        "total": fixed + sum(seen) + tail,
    }
    recorded = as_object(call.get("tokens"))
    return found + [
        f"{label}: {part} is {recorded.get(part)}, replay gives {expected[part]}"
        for part in expected
        if recorded.get(part) != expected[part]
    ]


def replay_problems(rows: Sequence[JsonObject], tokenizer: PromptTokenizer, mode: str) -> list[str]:
    section = tools_segment(tokenizer, load_tool_schemas().values())
    found: list[str] = []
    for row in rows:
        if "error" in row:
            continue
        case_id = str(row.get("case_id"))
        rules = rules_of(tokenizer, row, mode)
        if isinstance(rules, str):
            found.append(f"{case_id}: {rules}")
            continue
        for index, call in enumerate(model_calls(row)):
            found += call_problems(f"{case_id} call {index}", call, tokenizer, rules, section)
    return found
