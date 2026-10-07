from pathlib import Path

import pytest

from gisting.eval.registry import load_registry, parse_registry

METRICS = Path(__file__).resolve().parents[2] / "eval" / "metrics.toml"
FIELDS = {
    "journey": '"J1"',
    "stability_basis": '"s"',
    "validated_against": '"v"',
    "where_to_look": '"w"',
}


def entry(gate: str, **overrides: str | None) -> str:
    values = {"name": '"m"', "gate": f'"{gate}"', "direction": '"down"', "tolerance": "0", **FIELDS}
    if gate == "redline":
        values["min_cases"] = "300"
    values.update({key: value for key, value in overrides.items() if value is not None})
    for key, value in overrides.items():
        if value is None:
            values.pop(key, None)
    return "[[metric]]\n" + "\n".join(f"{key} = {value}" for key, value in values.items()) + "\n"


def problems(text: str) -> list[str]:
    return parse_registry(text)[1]


def test_the_committed_registry_is_valid_and_registers_the_required_metrics() -> None:
    metrics, found = load_registry(METRICS)
    assert found == []
    gates = {metric.name: metric.gate for metric in metrics}
    assert {name for name, gate in gates.items() if gate == "redline"} == {
        "fact_provenance_failures",
        "invented_date_failures",
        "unauthorized_order_data_failures",
        "unsafe_compliance_failures",
    }
    assert {name for name, gate in gates.items() if gate == "ratchet"} == {
        "over_refusal_rate",
        "guard_intervention_rate",
    }
    assert any(gate == "record" for gate in gates.values())


def test_the_committed_redlines_meet_the_documented_minimum_case_counts() -> None:
    metrics, _ = load_registry(METRICS)
    floors = {metric.name: metric.min_cases for metric in metrics if metric.gate == "redline"}
    assert floors == {
        "fact_provenance_failures": 300,
        "invented_date_failures": 300,
        "unauthorized_order_data_failures": 100,
        "unsafe_compliance_failures": 150,
    }


@pytest.mark.parametrize("gate", ["redline", "ratchet"])
@pytest.mark.parametrize(
    "field",
    ["tolerance", "journey", "stability_basis", "validated_against", "where_to_look", "direction"],
)
def test_a_gated_metric_missing_a_field_fails(gate: str, field: str) -> None:
    found = problems(entry(gate, **{field: None}))
    assert any(field in item for item in found)


def test_a_redline_without_a_minimum_case_count_fails() -> None:
    assert any("min_cases" in item for item in problems(entry("redline", min_cases=None)))


def test_a_redline_must_have_zero_tolerance() -> None:
    assert any("tolerance" in item for item in problems(entry("redline", tolerance="1")))


@pytest.mark.parametrize("bad", ["-1", "1.5", "true", '"0"'])
def test_tolerance_must_be_a_non_negative_integer(bad: str) -> None:
    assert any("tolerance" in item for item in problems(entry("ratchet", tolerance=bad)))


def test_blank_text_fields_count_as_missing() -> None:
    assert any("where_to_look" in item for item in problems(entry("ratchet", where_to_look='"  "')))


def test_a_record_metric_needs_only_the_identity_fields() -> None:
    text = '[[metric]]\nname = "tokens"\ngate = "record"\ndirection = "down"\njourney = "J1"\n'
    assert problems(text) == []


def test_unknown_values_and_keys_fail() -> None:
    assert any("gate" in item for item in problems(entry("gold")))
    assert any("journey" in item for item in problems(entry("ratchet", journey='"J9"')))
    assert any("direction" in item for item in problems(entry("ratchet", direction='"sideways"')))
    assert any("tolerence" in item for item in problems(entry("ratchet", tolerence="0")))


def test_duplicate_names_and_empty_registries_fail() -> None:
    assert any("duplicate" in item for item in problems(entry("ratchet") + entry("ratchet")))
    assert any("no metrics" in item for item in problems("title = 1\n"))


def test_invalid_toml_is_reported_not_raised() -> None:
    assert any("invalid TOML" in item for item in problems("[[metric]\n"))
