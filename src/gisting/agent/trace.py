from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from enum import StrEnum

from gisting.agent.knowledge import project_knowledge
from gisting.agent.policy import FallbackReason
from gisting.prompt.messages import AssistantMessage, Message, ToolMessage
from gisting.prompt.segments import PromptStats, total_stats

Document = Mapping[str, object]
MS_DIGITS = 1


@dataclass(frozen=True)
class GenerationRecord:
    prompt: PromptStats
    raw_output: str
    output_tokens: int
    first_token_ms: float
    total_ms: float
    finish_reason: str
    input_messages: tuple[Message, ...] = ()
    message_tokens: tuple[int, ...] = ()


@dataclass(frozen=True)
class ToolRecord:
    name: str | None
    arguments: object
    problem: str | None
    public: Document | None = None
    internal: Document | None = None
    result: str | None = None


@dataclass(frozen=True)
class GuardRecord:
    tool: str
    arguments: object
    status: str
    missing: tuple[str, ...]


@dataclass(frozen=True)
class FactCheckRecord:
    reason: str
    matched: str
    missing: tuple[str, ...]


@dataclass(frozen=True)
class ContextDropRecord:
    messages: int
    segments: int


class ReplySource(StrEnum):
    MODEL = "model"
    TEMPLATE = "template"
    FALLBACK = "fallback"
    CODE = "code"


@dataclass
class Recorder:
    generations: list[GenerationRecord] = field(default_factory=lambda: [])
    tools: list[ToolRecord] = field(default_factory=lambda: [])
    guards: list[GuardRecord] = field(default_factory=lambda: [])
    fact_checks: list[FactCheckRecord] = field(default_factory=lambda: [])
    reply_source: ReplySource = ReplySource.MODEL
    context_dropped: ContextDropRecord = field(default_factory=lambda: ContextDropRecord(0, 0))


@dataclass(frozen=True)
class Traces:
    public: Document
    internal: Document


def rounded(value: float) -> float:
    return round(value, MS_DIGITS)


@dataclass(frozen=True)
class RunContext:
    backend_id: str
    mode: str = "full"
    gist_run_id: str | None = None
    identity: Document = field(default_factory=lambda: {})
    known_ids: frozenset[str] = frozenset()


def public_tokens(stats: PromptStats) -> Document:
    return replace(stats, history=stats.history + stats.tool_results, tool_results=0).as_json()


def build_traces(
    recorder: Recorder, context: RunContext, wall_ms: float, fallback: FallbackReason | None
) -> Traces:
    stats = total_stats([record.prompt for record in recorder.generations])
    composition = stats.as_json()
    first = recorder.generations[0].first_token_ms if recorder.generations else 0.0
    latency = {"first_token_ms": rounded(first), "total_ms": rounded(wall_ms)}
    searched = [(r.name, r.result) for r in recorder.tools if not (r.internal or {}).get("reused")]
    knowledge = project_knowledge(searched, context.known_ids)
    public: Document = {
        "tools": [record.public for record in recorder.tools if record.public is not None],
        "knowledge": list(knowledge.public),
        "tokens": public_tokens(stats),
        "latency": latency,
    }
    internal: Document = {
        "backend_id": context.backend_id,
        "mode": context.mode,
        "gist_run_id": context.gist_run_id,
        "model": dict(context.identity),
        "fallback_reason": fallback.value if fallback else None,
        "reply_source": recorder.reply_source.value,
        "context_dropped": {
            "messages": recorder.context_dropped.messages,
            "segments": recorder.context_dropped.segments,
        },
        "knowledge_dropped": list(knowledge.dropped),
        "knowledge_truncated": list(knowledge.truncated),
        "knowledge_malformed": knowledge.malformed,
        "model_calls": [generation_json(record) for record in recorder.generations],
        "tool_calls": [tool_json(record) for record in recorder.tools],
        "guard": {
            "count": len(recorder.guards),
            "events": [guard_json(record) for record in recorder.guards],
        },
        "fact_check": {
            "count": len(recorder.fact_checks),
            "events": [fact_check_json(record) for record in recorder.fact_checks],
        },
        "tokens": composition,
        "latency": latency,
    }
    return Traces(public, internal)


def message_json(message: Message) -> Document:
    if isinstance(message, AssistantMessage):
        calls = [{"name": call.name, "arguments": call.arguments} for call in message.tool_calls]
        return {"role": "assistant", "content": message.content, "tool_calls": calls}
    role = "tool" if isinstance(message, ToolMessage) else "user"
    return {"role": role, "content": message.content, "tool_calls": []}


def generation_json(record: GenerationRecord) -> Document:
    return {
        "input_messages": [message_json(message) for message in record.input_messages],
        "message_tokens": list(record.message_tokens),
        "raw_output": record.raw_output,
        "output_tokens": record.output_tokens,
        "finish_reason": record.finish_reason,
        "tokens": record.prompt.as_json(),
        "first_token_ms": rounded(record.first_token_ms),
        "total_ms": rounded(record.total_ms),
    }


def tool_json(record: ToolRecord) -> Document:
    return {
        "name": record.name,
        "arguments": record.arguments,
        "problem": record.problem,
        "trace": record.internal,
        "result": record.result,
    }


def guard_json(record: GuardRecord) -> Document:
    return {
        "tool": record.tool,
        "arguments": record.arguments,
        "status": record.status,
        "missing": list(record.missing),
    }


def fact_check_json(record: FactCheckRecord) -> Document:
    return {
        "reason": record.reason,
        "matched": record.matched,
        "missing": list(record.missing),
    }
