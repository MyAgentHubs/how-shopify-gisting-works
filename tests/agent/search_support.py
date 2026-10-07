from dataclasses import replace

from agent_support import Rig, SpyTool, rig

from gisting.prompt.schema import ToolSchema
from gisting.tools.search_policy import SearchPolicy

SEARCH = "search_policy"
SCHEMA = ToolSchema(
    SEARCH,
    "Search the store policy.",
    {
        "type": "object",
        "properties": {"query": {"type": "string", "description": "Words to search for."}},
        "required": ["query"],
        "additionalProperties": False,
    },
)


def search_rig(*outputs: str) -> tuple[Rig, SpyTool]:
    subject = rig(*outputs)
    spy = SpyTool(SearchPolicy())
    deps = replace(
        subject.deps,
        tools={**subject.deps.tools, SEARCH: spy},
        schemas={**subject.deps.schemas, SEARCH: SCHEMA},
    )
    subject.deps = deps
    return subject, spy
