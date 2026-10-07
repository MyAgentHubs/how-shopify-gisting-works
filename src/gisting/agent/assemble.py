from collections.abc import Mapping
from dataclasses import dataclass, field

from gisting.agent.policy import AgentPolicyError, load_agent_policy
from gisting.agent.state import AgentDeps, ToolRunner
from gisting.model_server.interface import Model
from gisting.prompt.assemble import Rules, full_rules, gist_rules, tools_segment
from gisting.prompt.schema import SchemaError, load_tool_schemas
from gisting.prompt.tokenizer import PromptTokenizer
from gisting.shopify.demo_apply import UsageError
from gisting.shopify.jsonvalue import JsonObject
from gisting.tools.handoff import TOOL_NAME as HANDOFF_TOOL
from gisting.tools.handoff import HandoffToHuman
from gisting.tools.policy import LookupPolicy
from gisting.tools.reminder import TOOL_NAME as PRIORITY_TOOL
from gisting.tools.reminder import SendShippingReminder

LOOKUP_TOOL = "lookup_order"
GIST_MODE = "gist"


@dataclass(frozen=True)
class Loaded:
    model: Model
    tokenizer: PromptTokenizer
    gist_count: int | None = None
    gist_run_id: str | None = None
    identity: JsonObject = field(default_factory=lambda: {})


def production_tools(lookup: ToolRunner) -> dict[str, ToolRunner]:
    return {
        LOOKUP_TOOL: lookup,
        HANDOFF_TOOL: HandoffToHuman(),
        PRIORITY_TOOL: SendShippingReminder(),
    }


def rules_for(mode: str, loaded: Loaded) -> Rules:
    if mode != GIST_MODE:
        return full_rules(loaded.tokenizer)
    if loaded.gist_count is None:
        message = "--mode gist needs a loaded Gist artifact"
        raise UsageError(message)
    return gist_rules(loaded.tokenizer, loaded.gist_count)


def assemble_deps(
    loaded: Loaded, mode: str, tools: Mapping[str, ToolRunner], lookup: LookupPolicy
) -> AgentDeps:
    try:
        schemas = load_tool_schemas()
        policy = load_agent_policy()
        rules = rules_for(mode, loaded)
    except (SchemaError, AgentPolicyError, OSError) as error:
        message = f"{type(error).__name__}: {error}"
        raise UsageError(message) from error
    section = tools_segment(loaded.tokenizer, schemas.values())
    run_id = loaded.gist_run_id if mode == GIST_MODE else None
    return AgentDeps(
        loaded.model,
        loaded.tokenizer,
        tools,
        schemas,
        rules,
        section,
        policy,
        lookup,
        mode,
        run_id,
        loaded.identity,
    )
