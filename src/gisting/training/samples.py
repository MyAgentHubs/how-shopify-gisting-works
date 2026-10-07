import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from gisting.eval.case import Case
from gisting.prompt.messages import AssistantMessage, Message, ToolCall, ToolMessage, UserMessage
from gisting.shopify.jsonvalue import (
    Json,
    JsonObject,
    object_items,
    optional_str,
    required_list,
    required_object,
    required_str,
)

TOOL_NAME = "lookup_order"


@dataclass(frozen=True)
class Sample:
    id: str
    split: str
    category: str
    family: str
    kind: str
    scenario: str | None
    order_number: str | None
    email: str | None
    messages: tuple[Message, ...]

    @property
    def case(self) -> Case:
        return Case(
            self.category, self.kind, self.scenario, self.order_number, self.email, self.messages
        )


def message_json(message: Message) -> JsonObject:
    if isinstance(message, UserMessage):
        return {"role": "user", "content": message.content}
    if isinstance(message, ToolMessage):
        return {"role": "tool", "content": message.content}
    calls = [{"name": c.name, "arguments": dict(c.arguments)} for c in message.tool_calls]
    return {"role": "assistant", "content": message.content, "tool_calls": cast(Json, calls)}


def message_from_json(node: JsonObject) -> Message:
    role, content = required_str(node, "role"), required_str(node, "content")
    if role == "user":
        return UserMessage(content)
    if role == "tool":
        return ToolMessage(content)
    calls = tuple(
        ToolCall(required_str(call, "name"), required_object(call, "arguments"))
        for call in object_items(required_list(node, "tool_calls"), "tool_calls")
    )
    return AssistantMessage(content, calls)


def sample_json(sample: Sample) -> JsonObject:
    return {
        "id": sample.id,
        "split": sample.split,
        "category": sample.category,
        "family": sample.family,
        "kind": sample.kind,
        "scenario": sample.scenario,
        "order_number": sample.order_number,
        "email": sample.email,
        "messages": [message_json(message) for message in sample.messages],
    }


def sample_from_json(node: JsonObject) -> Sample:
    return Sample(
        id=required_str(node, "id"),
        split=required_str(node, "split"),
        category=required_str(node, "category"),
        family=required_str(node, "family"),
        kind=required_str(node, "kind"),
        scenario=optional_str(node, "scenario"),
        order_number=optional_str(node, "order_number"),
        email=optional_str(node, "email"),
        messages=tuple(
            message_from_json(item)
            for item in object_items(required_list(node, "messages"), "messages")
        ),
    )


def dump_jsonl(rows: Iterable[JsonObject]) -> str:
    return "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows)


def read_jsonl(path: Path) -> Iterator[JsonObject]:
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        row: Json = json.loads(line)
        if not isinstance(row, dict):
            message = f"{path}:{number} is not a JSON object"
            raise TypeError(message)
        yield row
