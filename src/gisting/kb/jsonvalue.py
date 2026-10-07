import json
from pathlib import Path
from typing import TypeAlias

Json: TypeAlias = dict[str, "Json"] | list["Json"] | str | int | float | bool | None
JsonObject: TypeAlias = dict[str, Json]
KB_DIR = Path(__file__).resolve().parents[3] / "kb"


class KbDataError(ValueError):
    pass


def parse_json(text: str, source: str) -> Json:
    try:
        return json.loads(text)
    except ValueError as error:
        message = f"{source}: not valid JSON: {error}"
        raise KbDataError(message) from error


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        message = f"{path.name}: cannot read: {error}"
        raise KbDataError(message) from error


def required_str(row: JsonObject, key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value or value != value.strip():
        message = f"field {key!r} must be a non-empty trimmed string"
        raise KbDataError(message)
    return value


def required_int(row: JsonObject, key: str) -> int:
    value = row.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        message = f"field {key!r} must be an integer"
        raise KbDataError(message)
    return value


def required_number(row: JsonObject, key: str) -> float:
    value = row.get(key)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        message = f"field {key!r} must be a number"
        raise KbDataError(message)
    return float(value)


def optional_strings(row: JsonObject, key: str) -> tuple[str, ...]:
    value = row.get(key, [])
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        message = f"field {key!r} must be a list of strings"
        raise KbDataError(message)
    return tuple(item for item in value if isinstance(item, str))
