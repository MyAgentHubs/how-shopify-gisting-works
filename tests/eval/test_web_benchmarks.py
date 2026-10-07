import json
from pathlib import Path
from typing import Any, cast

import pytest

from gisting.eval.web_benchmarks import Benchmarks, build_benchmarks
from gisting.shopify.jsonvalue import JsonObject, MalformedResponse

REPO = Path(__file__).resolve().parents[2]
TREE = "ee6c5c626278120523b9af02255958c0c9f5048c"
REPORTS = REPO / "eval" / "reports" / TREE
REDLINES = [
    "fact_provenance_failures",
    "invented_date_failures",
    "unauthorized_order_data_failures",
    "unsafe_compliance_failures",
]


def report(mode: str) -> JsonObject:
    return cast(JsonObject, json.loads((REPORTS / mode / "report.json").read_text("utf-8")))


def transcripts() -> list[JsonObject]:
    lines = (REPORTS / "gist" / "transcripts.jsonl").read_text("utf-8").splitlines()
    return [cast(JsonObject, json.loads(line)) for line in lines]


def build() -> Benchmarks:
    return build_benchmarks(report("full"), report("gist"), transcripts())


def raw_layers(mode: str, metric: str) -> dict[str, Any]:
    document: dict[str, Any] = json.loads((REPORTS / mode / "report.json").read_text("utf-8"))
    return document["metrics"][metric]["layers"]


def test_the_benchmarks_carry_the_token_use_of_each_mode() -> None:
    built = build()
    assert built.source.code_tree_sha == TREE
    assert built.tokens.full.rules_tokens_per_call == 526.0
    assert built.tokens.gist.rules_tokens_per_call == 19.0
    assert built.tokens.full.total_tokens_per_turn > built.tokens.gist.total_tokens_per_turn


def test_only_the_gated_red_lines_are_carried() -> None:
    built = build()
    assert [line.metric for line in built.red_lines] == REDLINES


def test_the_red_line_counts_match_the_reports_for_both_layers() -> None:
    built = build()
    for line in built.red_lines:
        for mode, source in (("full", line.results.full), ("gist", line.results.gist)):
            layers = raw_layers(mode, line.metric)
            assert (source.final.failures, source.final.n) == (
                layers["final"]["failures"],
                layers["final"]["n"],
            )
            assert source.raw.upper95 == layers["raw"]["upper95"]


def test_two_reports_of_the_same_mode_are_refused() -> None:
    with pytest.raises(MalformedResponse):
        build_benchmarks(report("full"), report("full"), transcripts())


def test_reports_of_different_runs_are_refused() -> None:
    other = report("gist")
    run = cast(JsonObject, other["run"])
    run["code_tree_sha"] = "0" * 40
    with pytest.raises(MalformedResponse):
        build_benchmarks(report("full"), other, transcripts())


def test_the_composition_carries_the_per_call_token_shape() -> None:
    composition = build().composition
    assert composition.tools_tokens_per_call == 395
    assert composition.chat_tokens_per_call == 47
    assert composition.prefix_tokens == 921
    assert composition.full_call_tokens == 968
    assert composition.gist_call_tokens == 461
    assert composition.saved_per_call == 507


def test_the_savings_per_turn_scale_the_per_call_saving_by_calls_per_case() -> None:
    composition = build().composition
    assert composition.calls_per_case == 908 / 933
    assert composition.saved_per_turn == 507 * 908 / 933
    assert round(composition.saved_per_turn, 1) == 493.4


def test_transcripts_with_a_different_call_count_are_refused() -> None:
    with pytest.raises(MalformedResponse):
        build_benchmarks(report("full"), report("gist"), transcripts()[:-1])


def test_transcripts_whose_calls_do_not_add_up_are_refused() -> None:
    rows = transcripts()
    first = next(row for row in rows if cast(JsonObject, row["internal"])["model_calls"])
    calls = cast(list[JsonObject], cast(JsonObject, first["internal"])["model_calls"])
    cast(JsonObject, calls[0]["tokens"])["tools"] = 1
    with pytest.raises(MalformedResponse):
        build_benchmarks(report("full"), report("gist"), rows)


def test_transcripts_whose_rules_differ_from_the_report_are_refused() -> None:
    rows = transcripts()
    for row in rows:
        for call in cast(list[JsonObject], cast(JsonObject, row["internal"])["model_calls"]):
            cast(JsonObject, call["tokens"])["rules"] = 20
    with pytest.raises(MalformedResponse):
        build_benchmarks(report("full"), report("gist"), rows)
