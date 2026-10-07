import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import cast

GATES = ("redline", "ratchet", "record")
DIRECTIONS = ("down", "up")
JOURNEYS = ("J1", "J2", "J3", "J4a", "J4b")
IDENTITY = ("name", "gate", "direction", "journey")
GATED_TEXT = ("stability_basis", "validated_against", "where_to_look")
OPTIONAL = ("tolerance", "min_cases", *GATED_TEXT)
NAME = re.compile(r"[a-z][a-z0-9_]*")
GATED = ("redline", "ratchet")
REDLINE_TOLERANCE = 0


@dataclass(frozen=True)
class Metric:
    name: str
    gate: str
    direction: str
    journey: str
    tolerance: int | None
    min_cases: int | None
    stability_basis: str | None
    validated_against: str | None
    where_to_look: str | None


def is_count(value: object, minimum: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= minimum


def is_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def identity_problems(entry: Mapping[str, object]) -> list[str]:
    found = [f"unknown key {key}" for key in entry if key not in (*IDENTITY, *OPTIONAL)]
    name = entry.get("name")
    if not isinstance(name, str) or not NAME.fullmatch(name):
        found.append("name must be snake_case text")
    for key, allowed in (("gate", GATES), ("direction", DIRECTIONS), ("journey", JOURNEYS)):
        if entry.get(key) not in allowed:
            found.append(f"{key} must be one of {', '.join(allowed)}")
    return found


def gated_problems(entry: Mapping[str, object]) -> list[str]:
    if entry.get("gate") not in GATED:
        return []
    found = [
        f"{key} is required for a gated metric" for key in GATED_TEXT if not is_text(entry.get(key))
    ]
    if not is_count(entry.get("tolerance"), 0):
        found.append("tolerance must be a non-negative integer number of cases")
    if entry.get("gate") == "redline":
        found += redline_problems(entry)
    return found


def redline_problems(entry: Mapping[str, object]) -> list[str]:
    found: list[str] = []
    if entry.get("tolerance") != REDLINE_TOLERANCE:
        found.append(f"tolerance of a redline must be {REDLINE_TOLERANCE}")
    if not is_count(entry.get("min_cases"), 1):
        found.append("min_cases must be a positive integer for a redline")
    return found


def entry_problems(entry: Mapping[str, object]) -> list[str]:
    return [*identity_problems(entry), *gated_problems(entry)]


def to_metric(entry: Mapping[str, object]) -> Metric:
    def text(key: str) -> str | None:
        value = entry.get(key)
        return value if isinstance(value, str) else None

    def count(key: str) -> int | None:
        value = entry.get(key)
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    return Metric(
        name=str(entry["name"]),
        gate=str(entry["gate"]),
        direction=str(entry["direction"]),
        journey=str(entry["journey"]),
        tolerance=count("tolerance"),
        min_cases=count("min_cases"),
        stability_basis=text("stability_basis"),
        validated_against=text("validated_against"),
        where_to_look=text("where_to_look"),
    )


def as_table(value: object) -> Mapping[str, object] | None:
    return cast(Mapping[str, object], value) if isinstance(value, dict) else None


def parse_registry(text: str) -> tuple[list[Metric], list[str]]:
    try:
        document = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        return [], [f"invalid TOML: {error}"]
    entries: object = document.get("metric")
    if not isinstance(entries, list) or not entries:
        return [], ["no metrics registered"]
    metrics: list[Metric] = []
    problems: list[str] = []
    for index, raw in enumerate(cast(list[object], entries), start=1):
        table = as_table(raw)
        found = ["entry must be a table"] if table is None else entry_problems(table)
        label = index if table is None else table.get("name", index)
        problems += [f"metric {label}: {item}" for item in found]
        if table is not None and not found:
            metrics.append(to_metric(table))
    names = [metric.name for metric in metrics]
    problems += [f"duplicate metric {name}" for name in sorted(set(names)) if names.count(name) > 1]
    return metrics, problems


def load_registry(path: Path) -> tuple[list[Metric], list[str]]:
    try:
        return parse_registry(path.read_text(encoding="utf-8"))
    except OSError as error:
        return [], [f"cannot read {path.name}: {error}"]
