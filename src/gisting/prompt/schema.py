import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from gisting.prompt.files import TOOLS_DIR

JSON_TYPES: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
}


class SchemaError(ValueError):
    pass


@dataclass(frozen=True)
class ToolSchema:
    name: str
    description: str
    parameters: Mapping[str, object]

    def function_json(self) -> dict[str, object]:
        function = {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }
        return {"type": "function", "function": function}


def as_object(value: object) -> dict[str, object] | None:
    return cast(dict[str, object], value) if isinstance(value, dict) else None


def object_at(parent: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = as_object(parent.get(key))
    if value is None:
        message = f"{key} must be an object"
        raise SchemaError(message)
    return value


def text_at(parent: Mapping[str, object], key: str) -> str:
    value = parent.get(key)
    if not isinstance(value, str) or not value:
        message = f"{key} must be a non-empty string"
        raise SchemaError(message)
    return value


def required_names(parameters: Mapping[str, object]) -> list[str]:
    required = parameters.get("required", [])
    if not isinstance(required, list) or not all(
        isinstance(name, str) for name in cast(list[object], required)
    ):
        message = "required must be a list of strings"
        raise SchemaError(message)
    return cast(list[str], required)


def check_parameters(parameters: Mapping[str, object]) -> None:
    properties = object_at(parameters, "properties")
    if parameters.get("type") != "object" or parameters.get("additionalProperties") is not False:
        message = "parameters must be an object type with additionalProperties false"
        raise SchemaError(message)
    if not set(required_names(parameters)) <= set(properties):
        message = "required must list declared properties"
        raise SchemaError(message)
    for name in properties:
        check_property(name, object_at(properties, name))


def check_property(name: str, node: Mapping[str, object]) -> None:
    kind = node.get("type")
    if not isinstance(kind, str) or kind not in JSON_TYPES:
        message = f"property {name} has an unsupported type"
        raise SchemaError(message)
    if "enum" in node and not enum_values_fit(node["enum"], kind):
        message = f"property {name} needs a non-empty enum of {kind} values"
        raise SchemaError(message)


def enum_values_fit(enum: object, kind: str) -> bool:
    values = cast(list[object], enum) if isinstance(enum, list) else []
    return bool(values) and all(has_type(value, kind) for value in values)


def parse_schema(document: object) -> ToolSchema:
    root = as_object(document)
    if root is None:
        message = "tool schema must be an object"
        raise SchemaError(message)
    parameters = object_at(root, "parameters")
    check_parameters(parameters)
    return ToolSchema(text_at(root, "name"), text_at(root, "description"), parameters)


def load_tool_schemas(directory: Path = TOOLS_DIR) -> dict[str, ToolSchema]:
    schemas: dict[str, ToolSchema] = {}
    for path in sorted(directory.glob("*.json")):
        try:
            schema = parse_schema(json.loads(path.read_text(encoding="utf-8")))
        except ValueError as error:
            message = f"{path.name}: {error}"
            raise SchemaError(message) from error
        schemas[schema.name] = schema
    return schemas


def has_type(value: object, type_name: str) -> bool:
    if isinstance(value, bool):
        return type_name == "boolean"
    return isinstance(value, JSON_TYPES[type_name])


def value_problem(name: str, value: object, node: Mapping[str, object]) -> str | None:
    expected = node.get("type")
    if not isinstance(expected, str) or not has_type(value, expected):
        return f"argument {name} must be of type {expected}"
    allowed = cast(list[object], node.get("enum", []))
    if allowed and value not in allowed:
        return f"argument {name} must be one of: {', '.join(str(item) for item in allowed)}"
    return None


def validate_arguments(schema: ToolSchema, arguments: object) -> str | None:
    given = as_object(arguments)
    if given is None:
        return "arguments must be a JSON object"
    properties = object_at(schema.parameters, "properties")
    for name in required_names(schema.parameters):
        if name not in given:
            return f"missing required argument: {name}"
    for name, value in given.items():
        if name not in properties:
            return f"unexpected argument: {name}"
        problem = value_problem(name, value, object_at(properties, name))
        if problem:
            return problem
    return None
