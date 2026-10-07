import json
from typing import Any, cast

INDENT = "  "
SCALARS = {
    "string": "string",
    "integer": "number",
    "number": "number",
    "boolean": "boolean",
    "null": "null",
}


def unsupported(node: dict[str, Any]) -> ValueError:
    return ValueError(f"unsupported schema node: {json.dumps(node, sort_keys=True)}")


def property_name(name: str) -> str:
    return name if name.isidentifier() else json.dumps(name)


def object_type(node: dict[str, Any], depth: int) -> str:
    properties: dict[str, Any] = node.get("properties", {})
    if not properties:
        extra = node.get("additionalProperties")
        if isinstance(extra, dict):
            return f"Readonly<Record<string, {ts_type(cast(dict[str, Any], extra), depth)}>>"
        raise unsupported(node)
    required = set(node.get("required", []))
    inner = INDENT * (depth + 1)
    lines = [
        f"{inner}readonly {property_name(name)}{'' if name in required else '?'}: "
        f"{ts_type(child, depth + 1)};"
        for name, child in properties.items()
    ]
    return "{\n" + "\n".join(lines) + "\n" + INDENT * depth + "}"


def array_type(node: dict[str, Any], depth: int) -> str:
    items = node["items"]
    item = ts_type(items, depth)
    is_union = "anyOf" in items or len(items.get("enum", [])) > 1
    return f"readonly {f'({item})' if is_union else item}[]"


def ts_type(node: dict[str, Any], depth: int) -> str:
    if "enum" in node:
        return " | ".join(json.dumps(value) for value in node["enum"])
    if "anyOf" in node:
        return " | ".join(ts_type(option, depth) for option in node["anyOf"])
    kind = node.get("type")
    if kind in SCALARS:
        return SCALARS[kind]
    if kind == "array":
        return array_type(node, depth)
    if kind == "object":
        return object_type(node, depth)
    raise unsupported(node)


def render_types(schema: dict[str, Any]) -> str:
    return f"export type {schema['title']} = {ts_type(schema, 0)};\n"
