import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Annotated

from gisting.eval.dataclass_json import decode_as
from gisting.prompt.schema_marks import MaxItems, Pattern

ISO_DATE = r"^\d{4}-\d{2}-\d{2}$"
MAX_STOPS = 32


@dataclass(frozen=True)
class ModelPrice:
    id: str
    name: str
    short: str
    input: float
    cache_read: float
    min_cacheable: int


@dataclass(frozen=True)
class Calculator:
    days_per_month: int
    default_per_day: int
    default_turns: int
    max_turns: int
    stops: Annotated[tuple[int, ...], MaxItems(MAX_STOPS)]
    chart_stops: Annotated[tuple[int, ...], MaxItems(MAX_STOPS)]


@dataclass(frozen=True)
class Pricing:
    source: str
    accessed: Annotated[str, Pattern(ISO_DATE)]
    default: str
    models: tuple[ModelPrice, ...]
    calculator: Calculator


def pricing_of(document: object) -> Pricing:
    return decode_as(Pricing, document)


def check_models(pricing: Pricing) -> None:
    ids = [model.id for model in pricing.models]
    if len(set(ids)) != len(ids):
        message = "duplicate model ids"
        raise ValueError(message)
    if pricing.default not in ids:
        message = "default is not a listed model"
        raise ValueError(message)
    for model in pricing.models:
        if model.cache_read > model.input:
            message = f"cache_read of {model.id} is above its input price"
            raise ValueError(message)


def check_calculator(calculator: Calculator) -> None:
    stops = calculator.stops
    if any(later <= earlier for earlier, later in zip(stops, stops[1:], strict=False)):
        message = "stops must strictly increase"
        raise ValueError(message)
    chart = calculator.chart_stops
    increasing = all(later > earlier for earlier, later in zip(chart, chart[1:], strict=False))
    if not chart or not increasing or not set(chart) <= set(stops):
        message = "chart_stops must be increasing and a subset of stops"
        raise ValueError(message)
    if calculator.default_per_day not in stops:
        message = "default_per_day must be one of the stops"
        raise ValueError(message)
    if not 1 <= calculator.default_turns <= calculator.max_turns:
        message = "default_turns must be between 1 and max_turns"
        raise ValueError(message)


def validate_pricing(pricing: Pricing) -> None:
    try:
        date.fromisoformat(pricing.accessed)
    except ValueError as error:
        message = "accessed is not a calendar date"
        raise ValueError(message) from error
    check_models(pricing)
    check_calculator(pricing.calculator)


def load_pricing(path: Path) -> Pricing:
    pricing = pricing_of(json.loads(path.read_text(encoding="utf-8")))
    validate_pricing(pricing)
    return pricing
