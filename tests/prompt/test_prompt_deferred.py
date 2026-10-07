from pathlib import Path

from gisting.prompt.files import PROMPTS_DIR, TOOLS_DIR
from gisting.prompt.schema import load_tool_schemas, validate_arguments

DEFERRED_DIR = PROMPTS_DIR / "deferred"
SOURCE_DIR = Path(__file__).resolve().parents[2] / "src"


def test_the_deferred_tool_schema_still_parses_and_validates_a_call() -> None:
    schemas = load_tool_schemas(DEFERRED_DIR)
    assert list(schemas) == ["search_policy"]
    schema = schemas["search_policy"]
    assert schema.function_json()["type"] == "function"
    assert validate_arguments(schema, {"query": "return period"}) is None
    assert validate_arguments(schema, {}) is not None


def test_no_production_tool_schema_is_a_deferred_one() -> None:
    assert not set(load_tool_schemas(DEFERRED_DIR)) & set(load_tool_schemas(TOOLS_DIR))


def test_no_source_file_loads_from_the_deferred_directory() -> None:
    loaders = [
        path.relative_to(SOURCE_DIR)
        for path in SOURCE_DIR.rglob("*.py")
        if "deferred" in path.read_text(encoding="utf-8")
    ]
    assert loaders == []
