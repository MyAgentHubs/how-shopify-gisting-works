from collections.abc import Iterable
from dataclasses import dataclass, field, replace

from gisting.agent.assemble import LOOKUP_TOOL, Loaded, assemble_deps, production_tools
from gisting.agent.state import AgentDeps, TurnResult
from gisting.agent.turn import run_turn
from gisting.prompt.messages import Message
from gisting.serve.contract import Mode
from gisting.serve.deadline import DeadlineModel, DeadlineTool
from gisting.serve.lookup_client import ClientFactory
from gisting.serve.scope import TurnScope
from gisting.shopify.jsonvalue import JsonObject
from gisting.tools.cache import OrderCache
from gisting.tools.handoff import TOOL_NAME as HANDOFF_TOOL
from gisting.tools.lookup_order import LookupDeps, LookupOrder, ToolResponse
from gisting.tools.policy import LookupPolicy
from gisting.tools.reminder import TOOL_NAME as PRIORITY_TOOL

FROZEN_TOOLS = frozenset({LOOKUP_TOOL, HANDOFF_TOOL, PRIORITY_TOOL})


class ToolSetMismatch(Exception):
    pass


class Unbuilt:
    def call(self, arguments: JsonObject, session_id: str) -> ToolResponse:
        message = "the tool set is being checked, not served"
        raise ToolSetMismatch(message)


@dataclass(frozen=True)
class LookupParts:
    client_for: ClientFactory
    cache: OrderCache
    policy: LookupPolicy
    email_secret: str = field(repr=False)


@dataclass(frozen=True)
class TurnRunner:
    gist: AgentDeps
    full: AgentDeps
    lookup: LookupParts

    def __call__(
        self,
        mode: Mode,
        session_id: str,
        history: list[Message],
        scope: TurnScope,
    ) -> TurnResult:
        base = self.gist if mode == "gist" else self.full
        parts = self.lookup
        deadline = scope.deadline
        client = parts.client_for(deadline)
        lookup_deps = LookupDeps(
            client, parts.cache, scope.failures, parts.policy, parts.email_secret, reads=scope.reads
        )
        tools = {
            name: DeadlineTool(tool, deadline)
            for name, tool in production_tools(LookupOrder(lookup_deps)).items()
        }
        agent_deps = replace(base, model=DeadlineModel(base.model, deadline), tools=tools)
        return run_turn(agent_deps, session_id, history)


def require_frozen_tools(tool_names: Iterable[str], schema_names: Iterable[str]) -> None:
    tools, schemas = frozenset(tool_names), frozenset(schema_names)
    if tools != FROZEN_TOOLS or schemas != FROZEN_TOOLS:
        expected = sorted(FROZEN_TOOLS)
        message = f"tools {sorted(tools)} and schemas {sorted(schemas)} must be {expected}"
        raise ToolSetMismatch(message)


def make_runner(gist: Loaded, full: Loaded, lookup: LookupParts) -> TurnRunner:
    gist_deps = assemble_deps(gist, "gist", {}, lookup.policy)
    full_deps = assemble_deps(full, "full", {}, lookup.policy)
    tools = production_tools(Unbuilt())
    require_frozen_tools(tools, gist_deps.schemas)
    require_frozen_tools(tools, full_deps.schemas)
    return TurnRunner(gist_deps, full_deps, lookup)
