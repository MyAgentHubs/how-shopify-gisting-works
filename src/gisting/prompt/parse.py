import json
import re
from dataclasses import dataclass
from typing import cast

from gisting.prompt.tokenizer import TOOL_CALL

CALL_BLOCK = re.compile(r"<tool_call>(.*?)</tool_call>", re.DOTALL)


@dataclass(frozen=True)
class CallRequest:
    name: str | None
    arguments: object
    problem: str | None


@dataclass(frozen=True)
class ParsedOutput:
    content: str
    calls: tuple[CallRequest, ...]


def parse_call(block: str) -> CallRequest:
    try:
        document: object = json.loads(block)
    except ValueError:
        return CallRequest(None, None, "tool call is not valid JSON")
    if not isinstance(document, dict):
        return CallRequest(None, None, "tool call must be a JSON object")
    fields = cast(dict[str, object], document)
    name = fields.get("name")
    if not isinstance(name, str) or "arguments" not in fields:
        return CallRequest(None, None, "tool call needs a name and arguments")
    return CallRequest(name, fields["arguments"], None)


def parse_output(text: str) -> ParsedOutput:
    calls = [parse_call(block) for block in CALL_BLOCK.findall(text)]
    remainder = CALL_BLOCK.sub("", text)
    if TOOL_CALL in remainder:
        calls.append(CallRequest(None, None, "tool call is incomplete"))
        remainder = remainder.split(TOOL_CALL)[0]
    return ParsedOutput(remainder.strip(), tuple(calls))
