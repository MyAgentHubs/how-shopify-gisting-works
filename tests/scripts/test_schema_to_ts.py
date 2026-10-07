import importlib
import json
import sys
from collections.abc import Callable
from typing import Any

import pytest
from conftest import SCRIPTS_DIR

REPO = SCRIPTS_DIR.parent
sys.path.insert(0, str(SCRIPTS_DIR))
render_types: Callable[[dict[str, Any]], str] = importlib.import_module("schema_to_ts").render_types


def render(schema: dict[str, Any]) -> str:
    return render_types({"title": "Thing", "type": "object", **schema})


def test_required_and_optional_properties() -> None:
    schema = {
        "properties": {"a": {"type": "string"}, "b": {"type": "integer"}},
        "required": ["a"],
    }
    assert render(schema) == (
        "export type Thing = {\n  readonly a: string;\n  readonly b?: number;\n};\n"
    )


def test_enum_union_and_nullable() -> None:
    schema = {
        "properties": {
            "level": {"enum": [1, "none"]},
            "name": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        },
        "required": ["level", "name"],
    }
    text = render(schema)
    assert '  readonly level: 1 | "none";\n' in text
    assert "  readonly name: string | null;\n" in text


def test_arrays_wrap_unions_and_nest_objects() -> None:
    schema = {
        "properties": {
            "tags": {"type": "array", "items": {"enum": ["x", "y"]}},
            "rows": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"ok": {"type": "boolean"}},
                    "required": ["ok"],
                },
            },
        },
        "required": ["tags", "rows"],
    }
    text = render(schema)
    assert '  readonly tags: readonly ("x" | "y")[];\n' in text
    assert "  readonly rows: readonly {\n    readonly ok: boolean;\n  }[];\n" in text


def test_string_map_becomes_a_readonly_record() -> None:
    schema = {
        "properties": {"m": {"type": "object", "additionalProperties": {"type": "string"}}},
        "required": ["m"],
    }
    assert "  readonly m: Readonly<Record<string, string>>;\n" in render(schema)


def test_property_names_that_are_not_identifiers_are_quoted() -> None:
    schema = {"properties": {"a-b": {"type": "string"}}, "required": ["a-b"]}
    assert '  readonly "a-b": string;\n' in render(schema)


def test_unsupported_schema_fails_loudly() -> None:
    with pytest.raises(ValueError, match="unsupported"):
        render({"properties": {"a": {"oneOf": []}}, "required": ["a"]})


def test_the_committed_eval_case_types_match_the_schema() -> None:
    schema = json.loads((REPO / "contracts/eval_case.schema.json").read_text(encoding="utf-8"))
    committed = (REPO / "contracts/eval_case.generated.ts").read_text(encoding="utf-8")
    assert render_types(schema) == committed
