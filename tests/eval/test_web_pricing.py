import json
from dataclasses import replace
from pathlib import Path

import pytest

from gisting.eval.dataclass_json import DecodeError
from gisting.eval.web_pricing import Pricing, load_pricing, pricing_of, validate_pricing

REPO = Path(__file__).resolve().parents[2]
PRICING_FILE = REPO / "apps" / "web" / "data" / "pricing.json"


def committed() -> Pricing:
    return load_pricing(PRICING_FILE)


def test_the_committed_prices_are_the_checked_ones() -> None:
    pricing = committed()
    assert pricing.source == "https://platform.claude.com/docs/en/about-claude/pricing"
    assert pricing.accessed == "2026-10-05"
    assert pricing.default == "sonnet-5-5"
    rows = {m.id: (m.input, m.cache_read, m.min_cacheable) for m in pricing.models}
    assert rows == {
        "sonnet-5-5": (2.0, 0.2, 512),
        "opus-5-5": (4.0, 0.2, 512),
        "haiku-4-5": (1.0, 0.1, 4096),
    }


def test_the_calculator_defaults_are_ten_thousand_conversations_of_three_turns() -> None:
    calculator = committed().calculator
    assert calculator.days_per_month == 30
    assert calculator.default_per_day == 10000
    assert calculator.default_turns == 3
    assert calculator.default_turns <= calculator.max_turns
    assert len(calculator.stops) == 13
    assert calculator.stops[0] == 100
    assert calculator.stops[-1] == 1000000


def test_the_bar_chart_has_five_of_the_stops() -> None:
    calculator = committed().calculator
    assert calculator.chart_stops == (100, 1000, 10000, 100000, 1000000)
    assert set(calculator.chart_stops) <= set(calculator.stops)


def test_chart_stops_that_are_not_stops_or_not_increasing_are_refused() -> None:
    pricing = committed()
    calculator = pricing.calculator
    foreign = replace(calculator, chart_stops=(100, 101))
    with pytest.raises(ValueError, match="chart_stops"):
        validate_pricing(replace(pricing, calculator=foreign))
    backwards = replace(calculator, chart_stops=(1000, 100))
    with pytest.raises(ValueError, match="chart_stops"):
        validate_pricing(replace(pricing, calculator=backwards))
    empty = replace(calculator, chart_stops=())
    with pytest.raises(ValueError, match="chart_stops"):
        validate_pricing(replace(pricing, calculator=empty))


def test_a_cache_read_price_above_the_input_price_is_refused() -> None:
    pricing = committed()
    broken = replace(pricing.models[0], cache_read=pricing.models[0].input + 1)
    with pytest.raises(ValueError, match="cache_read"):
        validate_pricing(replace(pricing, models=(broken, *pricing.models[1:])))


def test_a_default_model_that_is_not_listed_is_refused() -> None:
    with pytest.raises(ValueError, match="default"):
        validate_pricing(replace(committed(), default="missing"))


def test_an_access_date_that_is_not_a_date_is_refused() -> None:
    with pytest.raises(ValueError, match="accessed"):
        validate_pricing(replace(committed(), accessed="2026-13-45"))


def test_duplicate_model_ids_are_refused() -> None:
    pricing = committed()
    with pytest.raises(ValueError, match="duplicate"):
        validate_pricing(replace(pricing, models=(pricing.models[0], pricing.models[0])))


def test_stops_that_do_not_increase_or_miss_the_default_are_refused() -> None:
    pricing = committed()
    calculator = pricing.calculator
    unsorted = replace(calculator, stops=(*calculator.stops[1:], calculator.stops[0]))
    with pytest.raises(ValueError, match="stops"):
        validate_pricing(replace(pricing, calculator=unsorted))
    missing = replace(calculator, default_per_day=calculator.default_per_day + 1)
    with pytest.raises(ValueError, match="default_per_day"):
        validate_pricing(replace(pricing, calculator=missing))


def test_default_turns_above_the_maximum_are_refused() -> None:
    pricing = committed()
    broken = replace(pricing.calculator, default_turns=pricing.calculator.max_turns + 1)
    with pytest.raises(ValueError, match="default_turns"):
        validate_pricing(replace(pricing, calculator=broken))


def test_a_document_with_a_missing_or_extra_key_is_refused() -> None:
    document = json.loads(PRICING_FILE.read_text("utf-8"))
    without = {key: value for key, value in document.items() if key != "source"}
    with pytest.raises(DecodeError):
        pricing_of(without)
    with pytest.raises(DecodeError):
        pricing_of({**document, "secret": "x"})
