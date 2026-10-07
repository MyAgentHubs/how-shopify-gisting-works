import json
from dataclasses import asdict, dataclass

from gisting.prompt.rules import RULES_FILE, rules_text
from gisting.prompt.schema import load_tool_schemas

JSON_INDENT = 2


@dataclass(frozen=True)
class PublicTool:
    name: str
    description: str
    parameters: str


@dataclass(frozen=True)
class PublicRules:
    rules_file: str
    rules: str
    tools: tuple[PublicTool, ...]


def build_public_rules() -> PublicRules:
    tools = tuple(
        PublicTool(
            schema.name, schema.description, json.dumps(schema.parameters, indent=JSON_INDENT)
        )
        for schema in load_tool_schemas().values()
    )
    return PublicRules(RULES_FILE, rules_text(), tools)


def render_public_rules() -> str:
    return json.dumps(asdict(build_public_rules()), indent=JSON_INDENT) + "\n"
