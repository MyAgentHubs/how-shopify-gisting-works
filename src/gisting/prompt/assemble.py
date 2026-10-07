import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from gisting.prompt import tokenizer as tok
from gisting.prompt.files import read_prompt
from gisting.prompt.messages import AssistantMessage, Message, ToolCall, ToolMessage, UserMessage
from gisting.prompt.rules import rules_text
from gisting.prompt.schema import ToolSchema
from gisting.prompt.segments import Kind, Prompt, Segment
from gisting.prompt.tokenizer import PromptTokenizer

TOOLS_PREAMBLE_FILE = "qwen3_tools_preamble.txt"
TOOLS_POSTAMBLE_FILE = "qwen3_tools_postamble.txt"
SYSTEM_SEPARATOR = "\n\n"


@dataclass(frozen=True)
class Rules:
    ids: tuple[int, ...]


class Builder:
    def __init__(self, tokenizer: PromptTokenizer) -> None:
        self.tokenizer = tokenizer
        self.ids: list[int] = []

    def control(self, token: str) -> None:
        self.ids.append(self.tokenizer.control(token))

    def text(self, text: str) -> None:
        self.ids.extend(self.tokenizer.encode_text(text))

    def trusted(self, text: str) -> None:
        self.ids.extend(self.tokenizer.encode_trusted(text))


def segment(kind: Kind, build: Builder) -> Segment:
    return Segment(kind, tuple(build.ids))


def full_rules(tokenizer: PromptTokenizer, text: str | None = None) -> Rules:
    content = (rules_text() if text is None else text).strip()
    if not content:
        message = "rules text is empty"
        raise ValueError(message)
    return Rules(tuple(tokenizer.encode_text(content + SYSTEM_SEPARATOR)))


def gist_rules(tokenizer: PromptTokenizer, count: int) -> Rules:
    if count < 1:
        message = "gist rules need at least one placeholder"
        raise ValueError(message)
    return Rules((tokenizer.gist_placeholder,) * count)


def tools_text(schemas: Iterable[ToolSchema]) -> str:
    entries = "".join(
        "\n" + json.dumps(schema.function_json(), ensure_ascii=False) for schema in schemas
    )
    return read_prompt(TOOLS_PREAMBLE_FILE) + entries + "\n" + read_prompt(TOOLS_POSTAMBLE_FILE)


def tools_segment(tokenizer: PromptTokenizer, schemas: Iterable[ToolSchema]) -> Segment:
    build = Builder(tokenizer)
    build.trusted(tools_text(schemas))
    build.control(tok.IM_END)
    build.text("\n")
    return segment(Kind.TOOLS, build)


def rules_segment(tokenizer: PromptTokenizer, rules: Rules) -> Segment:
    build = Builder(tokenizer)
    build.control(tok.IM_START)
    build.text("system\n")
    build.ids.extend(rules.ids)
    return segment(Kind.RULES, build)


def render_user(build: Builder, message: UserMessage) -> None:
    build.control(tok.IM_START)
    build.text("user\n" + message.content)
    build.control(tok.IM_END)
    build.text("\n")


def render_call(build: Builder, call: ToolCall) -> None:
    arguments = json.dumps(dict(call.arguments), ensure_ascii=False)
    build.control(tok.TOOL_CALL)
    build.text(f'\n{{"name": "{call.name}", "arguments": {arguments}}}\n')
    build.control(tok.TOOL_CALL_END)


def render_assistant(build: Builder, message: AssistantMessage) -> None:
    build.control(tok.IM_START)
    lead = "assistant\n" + message.content
    if not message.tool_calls:
        build.text(lead)
    separators = [lead + "\n" if message.content else lead, *["\n"] * len(message.tool_calls)]
    for separator, call in zip(separators, message.tool_calls, strict=False):
        build.text(separator)
        render_call(build, call)
    build.control(tok.IM_END)
    build.text("\n")


def render_tool(build: Builder, message: ToolMessage, *, first: bool, last: bool) -> None:
    if first:
        build.control(tok.IM_START)
    build.text(("user" if first else "") + "\n")
    build.control(tok.TOOL_RESPONSE)
    build.text("\n" + message.content + "\n")
    build.control(tok.TOOL_RESPONSE_END)
    if last:
        build.control(tok.IM_END)
        build.text("\n")


def generation_prompt(build: Builder) -> None:
    build.control(tok.IM_START)
    build.text("assistant\n")
    for piece in build.tokenizer.variant.generation_suffix:
        if piece.is_control:
            build.control(piece.text)
        else:
            build.text(piece.text)


def message_segments(tokenizer: PromptTokenizer, messages: Sequence[Message]) -> list[Segment]:
    segments: list[Segment] = []
    for index, message in enumerate(messages):
        build = Builder(tokenizer)
        if isinstance(message, UserMessage):
            render_user(build, message)
        elif isinstance(message, AssistantMessage):
            render_assistant(build, message)
        else:
            first = index == 0 or not isinstance(messages[index - 1], ToolMessage)
            last = index == len(messages) - 1 or not isinstance(messages[index + 1], ToolMessage)
            render_tool(build, message, first=first, last=last)
        kind = Kind.TOOL_RESULTS if isinstance(message, ToolMessage) else Kind.HISTORY
        segments.append(segment(kind, build))
    return segments


def assemble(
    tokenizer: PromptTokenizer, rules: Rules, tools: Segment, messages: Sequence[Message]
) -> Prompt:
    tail = Builder(tokenizer)
    generation_prompt(tail)
    segments = [
        rules_segment(tokenizer, rules),
        tools,
        *message_segments(tokenizer, messages),
        segment(Kind.HISTORY, tail),
    ]
    return Prompt(tuple(segments))
