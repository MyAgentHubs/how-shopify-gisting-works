from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol

from gisting.agent.consent import latest_exchange
from gisting.agent.guard import (
    ask_reply,
    related_to_order,
)
from gisting.agent.policy import AgentPolicy, FallbackReason
from gisting.agent.trace import (
    FactCheckRecord,
    Recorder,
    ReplySource,
    Traces,
)
from gisting.model_server.interface import Model
from gisting.prompt.assemble import Rules
from gisting.prompt.messages import Message, ToolMessage
from gisting.prompt.schema import ToolSchema
from gisting.prompt.segments import Segment
from gisting.prompt.tokenizer import PromptTokenizer
from gisting.shopify.jsonvalue import JsonObject
from gisting.tools.lookup_order import ToolResponse
from gisting.tools.policy import LookupPolicy

UNRELATED_ASK = "ask_without_order_context"


class ToolRunner(Protocol):
    def call(self, arguments: JsonObject, session_id: str) -> ToolResponse: ...


@dataclass(frozen=True)
class AgentDeps:
    model: Model
    tokenizer: PromptTokenizer
    tools: Mapping[str, ToolRunner]
    schemas: Mapping[str, ToolSchema]
    rules: Rules
    tools_section: Segment
    policy: AgentPolicy
    lookup: LookupPolicy
    mode: str = "full"
    gist_run_id: str | None = None
    identity: JsonObject = field(default_factory=lambda: {})
    policy_answers: frozenset[str] = frozenset()
    policy_ids: frozenset[str] = frozenset()


@dataclass(frozen=True)
class TurnResult:
    answer: str
    fallback_reason: FallbackReason | None
    traces: Traces


@dataclass
class TurnState:
    messages: list[Message]
    recorder: Recorder = field(default_factory=Recorder)
    calls_made: int = 0
    invalid_calls: int = 0
    results: dict[str, ToolMessage] = field(default_factory=lambda: {})
    result_types: dict[str, str] = field(default_factory=lambda: {})
    batch: list[str] = field(default_factory=lambda: [])


@dataclass(frozen=True)
class Done:
    answer: str
    fallback_reason: FallbackReason | None = None
    source: ReplySource = ReplySource.MODEL


def fallback(deps: AgentDeps, reason: FallbackReason) -> Done:
    return Done(deps.policy.fallback_replies[reason], reason, ReplySource.FALLBACK)


def ask(deps: AgentDeps, missing: list[str]) -> Done:
    return Done(ask_reply(deps.policy, missing), None, ReplySource.TEMPLATE)


def declined_unrelated(
    deps: AgentDeps, state: TurnState, source: str, missing: list[str]
) -> Done | None:
    said, previous = latest_exchange(state.messages)
    if related_to_order(deps.policy, said, previous):
        return None
    state.recorder.fact_checks.append(FactCheckRecord(UNRELATED_ASK, source, tuple(missing)))
    return Done(deps.policy.answers.refusal, None, ReplySource.TEMPLATE)


def need_consent(deps: AgentDeps, tool: str) -> Done:
    return Done(deps.policy.needs_consent_replies[tool], None, ReplySource.TEMPLATE)


def replaced(state: TurnState, reason: str, matched: str, reply: str) -> Done:
    state.recorder.fact_checks.append(FactCheckRecord(reason, matched, ()))
    return Done(reply, None, ReplySource.TEMPLATE)


def executed(state: TurnState, names: set[str]) -> bool:
    return any(r.name in names and r.internal is not None for r in state.recorder.tools)
