import math
import re
import types
from collections.abc import Callable
from dataclasses import MISSING, fields, is_dataclass
from typing import Annotated, Literal, TypeVar, Union, cast, get_args, get_origin, get_type_hints

from gisting.prompt.schema_marks import MaxItems, MaxLength, Pattern

T = TypeVar("T")
SCALAR_TYPES: dict[object, str] = {str: "string", int: "integer", float: "number", bool: "boolean"}
SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"
NO_EXTRA_KEYS: dict[str, object] = dict(additionalProperties=False)
UNIONS: tuple[object, ...] = (Union, types.UnionType)


class DecodeError(ValueError):
    pass


def fail(path: str, reason: str) -> DecodeError:
    return DecodeError(f"{path.lstrip('.') or '$'}: {reason}")


def split_annotated(tp: object) -> tuple[object, tuple[object, ...]]:
    if get_origin(tp) is Annotated:
        arguments = get_args(tp)
        return arguments[0], arguments[1:]
    return tp, ()


def optional_member(tp: object) -> object:
    members = [member for member in get_args(tp) if member is not type(None)]
    if len(members) != 1:
        message = f"only X | None unions are supported, got {tp}"
        raise TypeError(message)
    return members[0]


def required_names(cls: type) -> list[str]:
    return [field.name for field in fields(cls) if field.default is MISSING]


def object_schema(cls: type) -> dict[str, object]:
    hints = get_type_hints(cls, include_extras=True)
    names = [field.name for field in fields(cls)]
    return {
        "type": "object",
        "properties": {name: schema_of(hints[name]) for name in names},
        "required": required_names(cls),
        **NO_EXTRA_KEYS,
    }


def shape_schema(tp: object) -> dict[str, object]:
    origin = get_origin(tp)
    arguments = get_args(tp)
    if tp in SCALAR_TYPES:
        return {"type": SCALAR_TYPES[tp]}
    if origin is Literal:
        return {"enum": list(arguments)}
    if origin is tuple:
        return {"type": "array", "items": schema_of(arguments[0])}
    if origin is dict:
        return {"type": "object", "additionalProperties": schema_of(arguments[1])}
    if origin in UNIONS:
        return {"anyOf": [schema_of(optional_member(tp)), {"type": "null"}]}
    if isinstance(tp, type) and is_dataclass(tp):
        return object_schema(tp)
    message = f"unsupported type {tp}"
    raise TypeError(message)


def mark_keywords(extra: object) -> dict[str, object]:
    if isinstance(extra, Pattern):
        return {"pattern": extra.regex}
    if isinstance(extra, MaxItems):
        return {"maxItems": extra.count}
    if isinstance(extra, MaxLength):
        return {"maxLength": extra.chars}
    return {}


def schema_of(tp: object) -> dict[str, object]:
    base, extras = split_annotated(tp)
    node = shape_schema(base)
    for extra in extras:
        node.update(mark_keywords(extra))
    return node


def json_schema(cls: type) -> dict[str, object]:
    return {"$schema": SCHEMA_DIALECT, "title": cls.__name__, **object_schema(cls)}


def decode_float(value: int | float, path: str) -> float:
    try:
        number = float(value)
    except OverflowError:
        number = math.inf
    if not math.isfinite(number):
        raise fail(path, "expected a finite number")
    return number


def decode_scalar(tp: object, value: object, path: str) -> object:
    if tp is float and isinstance(value, (int, float)) and not isinstance(value, bool):
        return decode_float(value, path)
    if type(value) is not tp:
        raise fail(path, f"expected {SCALAR_TYPES[tp]}")
    return value


def decode_literal(tp: object, value: object, path: str) -> object:
    if not any(value == option and type(value) is type(option) for option in get_args(tp)):
        raise fail(path, f"expected one of {list(get_args(tp))}")
    return value


def decode_tuple(tp: object, value: object, path: str) -> object:
    if not isinstance(value, list):
        raise fail(path, "expected array")
    item = get_args(tp)[0]
    entries = cast(list[object], value)
    return tuple(decode(item, entry, f"{path}[{index}]") for index, entry in enumerate(entries))


def decode_dict(tp: object, value: object, path: str) -> object:
    if not isinstance(value, dict):
        raise fail(path, "expected object")
    item = get_args(tp)[1]
    entries = cast(dict[object, object], value)
    for key in entries:
        if not isinstance(key, str):
            raise fail(path, "object keys must be strings")
    return {key: decode(item, entry, f"{path}.{key}") for key, entry in entries.items()}


def decode_optional(tp: object, value: object, path: str) -> object:
    return None if value is None else decode(optional_member(tp), value, path)


def decode_dataclass(cls: type, value: object, path: str) -> object:
    if not isinstance(value, dict):
        raise fail(path, "expected object")
    entries = cast(dict[str, object], value)
    hints = get_type_hints(cls, include_extras=True)
    names = [field.name for field in fields(cls)]
    unknown = sorted(set(entries) - set(names))
    missing = [name for name in required_names(cls) if name not in entries]
    if unknown or missing:
        raise fail(path, f"unknown keys {unknown}, missing keys {missing}")
    return cls(**{
        name: decode(hints[name], entries[name], f"{path}.{name}")
        for name in names
        if name in entries
    })


ORIGIN_DECODERS: dict[object, Callable[[object, object, str], object]] = {
    Literal: decode_literal,
    tuple: decode_tuple,
    dict: decode_dict,
    Union: decode_optional,
    types.UnionType: decode_optional,
}


def decode_shape(tp: object, value: object, path: str) -> object:
    if tp in SCALAR_TYPES:
        return decode_scalar(tp, value, path)
    handler = ORIGIN_DECODERS.get(get_origin(tp))
    if handler:
        return handler(tp, value, path)
    if isinstance(tp, type) and is_dataclass(tp):
        return decode_dataclass(tp, value, path)
    message = f"unsupported type {tp}"
    raise TypeError(message)


def mark_violation(extra: object, decoded: object) -> str | None:
    if isinstance(extra, Pattern) and not re.search(extra.regex, cast(str, decoded)):
        return f"does not match {extra.regex}"
    if isinstance(extra, MaxItems) and len(cast(tuple[object, ...], decoded)) > extra.count:
        return f"has more than {extra.count} items"
    if isinstance(extra, MaxLength) and len(cast(str, decoded)) > extra.chars:
        return f"is longer than {extra.chars} characters"
    return None


def decode(tp: object, value: object, path: str = "") -> object:
    base, extras = split_annotated(tp)
    decoded = decode_shape(base, value, path)
    for extra in extras:
        violation = mark_violation(extra, decoded)
        if violation is not None:
            raise fail(path, violation)
    return decoded


def decode_as(cls: type[T], value: object) -> T:
    return cast(T, decode_dataclass(cls, value, ""))
