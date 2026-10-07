import re
from dataclasses import MISSING, fields, is_dataclass
from typing import Annotated, Literal, cast, get_args, get_origin, get_type_hints

from gisting.prompt.schema_marks import MaxItems, MaxLength, Pattern

SCALARS = (str, int, float)


class TraceRejected(ValueError):
    pass


def reject(path: str, reason: str) -> TraceRejected:
    return TraceRejected(f"{path or '$'}: {reason}")


def decode_scalar(tp: type, value: object, path: str) -> object:
    if tp is float and type(value) is int:
        return float(value)
    if type(value) is not tp:
        raise reject(path, f"expected {tp.__name__}")
    return value


def decode_literal(tp: object, value: object, path: str) -> object:
    if not any(value == option and type(value) is type(option) for option in get_args(tp)):
        raise reject(path, "not an allowed value")
    return value


def decode_tuple(tp: object, value: object, path: str) -> object:
    if not isinstance(value, list | tuple):
        raise reject(path, "expected array")
    item = get_args(tp)[0]
    entries = cast(list[object], value)
    return tuple(decode(item, entry, f"{path}[{index}]") for index, entry in enumerate(entries))


def decode_optional(tp: object, value: object, path: str) -> object:
    members = [member for member in get_args(tp) if member is not type(None)]
    return None if value is None else decode(members[0], value, path)


def decode_dataclass(cls: type, value: object, path: str) -> object:
    if not isinstance(value, dict):
        raise reject(path, "expected object")
    entries = cast(dict[str, object], value)
    hints = get_type_hints(cls, include_extras=True)
    values: dict[str, object] = {}
    for field in fields(cls):
        if field.name in entries:
            values[field.name] = decode(
                hints[field.name], entries[field.name], f"{path}.{field.name}"
            )
        elif field.default is MISSING:
            raise reject(f"{path}.{field.name}", "missing")
    return cls(**values)


def decode_shape(tp: object, value: object, path: str) -> object:
    origin = get_origin(tp)
    if origin is Literal:
        return decode_literal(tp, value, path)
    if origin is tuple:
        return decode_tuple(tp, value, path)
    if origin is not None:
        return decode_optional(tp, value, path)
    if isinstance(tp, type) and is_dataclass(tp):
        return decode_dataclass(tp, value, path)
    if tp in SCALARS:
        return decode_scalar(cast(type, tp), value, path)
    message = f"unsupported type {tp}"
    raise TypeError(message)


def violation(extra: object, decoded: object) -> str | None:
    if isinstance(extra, Pattern) and re.fullmatch(extra.regex, cast(str, decoded)) is None:
        return "does not match the pattern"
    if isinstance(extra, MaxItems) and len(cast(tuple[object, ...], decoded)) > extra.count:
        return "has too many items"
    if isinstance(extra, MaxLength) and len(cast(str, decoded)) > extra.chars:
        return "is too long"
    return None


def decode(tp: object, value: object, path: str = "") -> object:
    base, extras = (get_args(tp)[0], get_args(tp)[1:]) if get_origin(tp) is Annotated else (tp, ())
    decoded = decode_shape(base, value, path)
    for extra in extras:
        problem = violation(extra, decoded)
        if problem is not None:
            raise reject(path, problem)
    return decoded


def encode(value: object) -> object:
    if isinstance(value, tuple):
        return [encode(item) for item in cast(tuple[object, ...], value)]
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: encode(getattr(value, field.name)) for field in fields(value)}
    return value


def round_trip(cls: type, value: object) -> dict[str, object]:
    return cast(dict[str, object], encode(decode_dataclass(cls, value, "")))
