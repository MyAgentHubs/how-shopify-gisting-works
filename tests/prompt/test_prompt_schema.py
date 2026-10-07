import json
from pathlib import Path

import pytest

from gisting.prompt.schema import SchemaError, as_object, load_tool_schemas, validate_arguments

GOOD = {"order_number": "#1042", "email": "someone@example.com"}


def test_the_repo_schema_loads_and_renders_as_a_function() -> None:
    schemas = load_tool_schemas()
    assert list(schemas) == ["handoff_to_human", "lookup_order", "send_shipping_reminder"]
    function = schemas["lookup_order"].function_json()
    assert function["type"] == "function"
    inner = as_object(function["function"])
    assert inner is not None
    assert set(inner) == {"name", "description", "parameters"}


def test_valid_arguments_pass() -> None:
    assert validate_arguments(load_tool_schemas()["lookup_order"], GOOD) is None


@pytest.mark.parametrize(
    ("arguments", "reason"),
    [
        ({"order_number": "#1"}, "missing required argument: email"),
        ({**GOOD, "session_id": "s"}, "unexpected argument: session_id"),
        ({**GOOD, "email": 5}, "argument email must be of type string"),
        ({**GOOD, "order_number": None}, "argument order_number must be of type string"),
        ([], "arguments must be a JSON object"),
        ("order", "arguments must be a JSON object"),
    ],
)
def test_invalid_arguments_name_the_problem(arguments: object, reason: str) -> None:
    assert validate_arguments(load_tool_schemas()["lookup_order"], arguments) == reason


def test_booleans_are_not_integers(tmp_path: Path) -> None:
    schema = {
        "name": "t",
        "description": "d",
        "parameters": {
            "type": "object",
            "properties": {"n": {"type": "integer"}, "f": {"type": "boolean"}},
            "required": ["n"],
            "additionalProperties": False,
        },
    }
    (tmp_path / "t.json").write_text(json.dumps(schema))
    loaded = load_tool_schemas(tmp_path)["t"]
    assert validate_arguments(loaded, {"n": 1, "f": True}) is None
    assert validate_arguments(loaded, {"n": True}) == "argument n must be of type integer"
    assert validate_arguments(loaded, {"n": 1, "f": 1}) == "argument f must be of type boolean"


def test_a_value_outside_the_declared_enum_is_named_in_the_problem(tmp_path: Path) -> None:
    schema = {
        "name": "t",
        "description": "d",
        "parameters": {
            "type": "object",
            "properties": {"kind": {"type": "string", "enum": ["a", "b"]}},
            "required": ["kind"],
            "additionalProperties": False,
        },
    }
    (tmp_path / "t.json").write_text(json.dumps(schema))
    loaded = load_tool_schemas(tmp_path)["t"]
    assert validate_arguments(loaded, {"kind": "a"}) is None
    assert validate_arguments(loaded, {"kind": "c"}) == "argument kind must be one of: a, b"


@pytest.mark.parametrize(
    "document",
    [
        "[]",
        "{",
        '{"name": "t", "description": "d"}',
        '{"name": "", "description": "d", "parameters": {}}',
        '{"name": "t", "description": "d", "parameters": {"type": "object", "properties": {}}}',
        (
            '{"name": "t", "description": "d", "parameters": {"type": "object", '
            '"properties": {"a": {"type": "string"}}, "required": ["b"], '
            '"additionalProperties": false}}'
        ),
        (
            '{"name": "t", "description": "d", "parameters": {"type": "object", '
            '"properties": {"a": {"type": "array"}}, "additionalProperties": false}}'
        ),
        (
            '{"name": "t", "description": "d", "parameters": {"type": "object", '
            '"properties": {"a": {"type": "string", "enum": []}}, "additionalProperties": false}}'
        ),
        (
            '{"name": "t", "description": "d", "parameters": {"type": "object", '
            '"properties": {"a": {"type": "string", "enum": [1]}}, "additionalProperties": false}}'
        ),
    ],
)
def test_malformed_schema_files_are_rejected(tmp_path: Path, document: str) -> None:
    (tmp_path / "t.json").write_text(document)
    with pytest.raises(SchemaError):
        load_tool_schemas(tmp_path)


def test_the_handoff_tool_takes_no_arguments_so_the_model_cannot_pick_a_reason() -> None:
    schema = load_tool_schemas()["handoff_to_human"]
    assert schema.parameters["properties"] == {}
    assert validate_arguments(schema, {}) is None
    assert validate_arguments(schema, {"reason": "delayed"}) == "unexpected argument: reason"
