import json

from gisting.prompt.files import TOOLS_DIR
from gisting.prompt.public_rules import build_public_rules, render_public_rules
from gisting.prompt.rules import RULES_FILE, rules_text
from gisting.prompt.schema import load_tool_schemas

PRODUCTION_TOOLS = {"lookup_order", "handoff_to_human", "send_shipping_reminder"}


def test_the_public_rules_are_the_rendered_rules_the_model_reads() -> None:
    shown = build_public_rules()
    assert shown.rules == rules_text()
    assert shown.rules_file == RULES_FILE
    assert "{" not in shown.rules


def test_the_public_tools_are_exactly_the_production_tool_files() -> None:
    names = {tool.name for tool in build_public_rules().tools}
    assert names == {path.stem for path in TOOLS_DIR.glob("*.json")}
    assert names == PRODUCTION_TOOLS


def test_a_deferred_policy_tool_is_not_shown() -> None:
    assert "search_policy" not in render_public_rules()


def test_each_tool_shows_its_description_and_parameters_as_the_model_reads_them() -> None:
    schemas = load_tool_schemas()
    for tool in build_public_rules().tools:
        assert tool.description == schemas[tool.name].description
        assert json.loads(tool.parameters) == schemas[tool.name].parameters


def test_the_rendered_file_is_json_ending_in_one_newline() -> None:
    text = render_public_rules()
    assert text.endswith("}\n")
    assert json.loads(text)["rules"] == rules_text()
