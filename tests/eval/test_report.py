import copy
import json
from pathlib import Path
from typing import Any

import pytest
from fakes.agent_launch import inprocess_launcher

from gisting.eval.case_files import load_cases, plan_canaries
from gisting.eval.judging import GUARD_SOURCES
from gisting.eval.report import ReportError, build_report, load_rows
from gisting.eval.runner import RunSpec, Selection, run_cases, select_cases
from gisting.eval.stats import upper_bound
from gisting.prompt.phrases import load_phrases

ROOT = Path(__file__).resolve().parents[2]
SECRET = "report-test-secret-value"
LOADED, _PROBLEMS = load_cases(ROOT)
CASES = {item.case.id: item.case for item in LOADED}
CANARIES = plan_canaries(ROOT, "shipment-plan-v1.json") or {}
SHA = "t" * 40
DECLINE = load_phrases().sentences["decline_reply"]


@pytest.fixture(scope="module")
def transcripts(tmp_path_factory: pytest.TempPathFactory) -> Path:
    directory = tmp_path_factory.mktemp("transcripts")
    env_file = directory / "empty.env"
    env_file.write_text("")
    mp = pytest.MonkeyPatch()
    mp.setenv("GISTING_EMAIL_SECRET", SECRET)
    try:
        cases = select_cases(LOADED, Selection(("dev",), per_red_line=3))
        spec = RunSpec(ROOT, "full", directory, inprocess_launcher(env_file), env_file=env_file)
        return run_cases(spec, cases).path
    finally:
        mp.undo()


def report_of(rows: list[dict[str, Any]], text: str = "") -> dict[str, Any]:
    return json.loads(json.dumps(build_report(rows, CASES, ROOT, SHA, text)))


def rows_of(path: Path) -> list[dict[str, Any]]:
    return [dict(row) for row in load_rows(path)]


def row_for(rows: list[dict[str, Any]], red_line: str) -> dict[str, Any]:
    return next(row for row in rows if str(CASES[row["case_id"]].red_line) == red_line)


def test_the_report_names_the_run_and_counts_every_case(transcripts: Path) -> None:
    text = transcripts.read_text(encoding="utf-8")
    report = report_of(rows_of(transcripts), text)
    assert report["version"] == 1
    run = report["run"]
    assert run["code_tree_sha"] == SHA
    assert (run["mode"], run["backend_id"], run["gist_run_id"]) == ("full", "fake-rule-model", None)
    assert run["decoding"]["sampling"] == "greedy"
    assert run["decoding"]["max_new_tokens"] == 320
    assert len(run["rules_version"]) == 16
    cases = report["cases"]
    assert (cases["transcripts"], cases["graded"], cases["complete"]) == (12, 12, True)
    assert cases["by_red_line"] == {"1": 3, "3": 3, "4": 3, "none": 3}
    assert cases["splits"] == ["dev"]
    assert len(cases["transcripts_sha256"]) == 64


def test_every_metric_reports_counts_and_the_upper_bound_per_layer(transcripts: Path) -> None:
    metrics = report_of(rows_of(transcripts))["metrics"]
    assert set(metrics) == {
        "fact_provenance_failures",
        "invented_date_failures",
        "unauthorized_order_data_failures",
        "unsafe_compliance_failures",
        "over_refusal_rate",
        "guard_intervention_rate",
    }
    facts = metrics["fact_provenance_failures"]
    assert facts["gate"] == "redline"
    assert facts["enough_cases"] is False
    assert set(facts["layers"]) == {"raw", "final"}
    assert facts["layers"]["final"]["n"] == 3
    assert facts["layers"]["final"]["failures"] == 0
    assert facts["layers"]["final"]["upper95"] == round(upper_bound(0, 3), 6)
    assert metrics["unauthorized_order_data_failures"]["layers"]["final"]["n"] == 12
    assert set(metrics["guard_intervention_rate"]["layers"]) == {"final"}
    assert metrics["over_refusal_rate"]["layers"]["raw"]["n"] == 3


def test_tokens_are_averaged_per_turn_that_called_the_model(transcripts: Path) -> None:
    rows = rows_of(transcripts)
    tokens = report_of(rows)["tokens"]
    assert tokens["turns"] == len([row for row in rows if row["internal"]["model_calls"]])
    assert 0 < tokens["turns"] <= 12
    assert tokens["prefill_tokens_per_turn"] > 0
    assert tokens["total_tokens_per_turn"] >= tokens["prefill_tokens_per_turn"]
    assert tokens["rules_tokens_per_call"] > 0
    assert tokens["gist_token_count"] is None


def test_the_same_transcripts_always_give_the_same_report(transcripts: Path) -> None:
    rows = rows_of(transcripts)
    assert report_of(rows) == report_of(copy.deepcopy(rows))


def test_an_invented_weekday_in_the_answer_fails_the_final_layer_only(transcripts: Path) -> None:
    rows = rows_of(transcripts)
    row = row_for(rows, "1")
    row["answer"] = "Good news, it arrives on Friday."
    layers = report_of(rows)["metrics"]["fact_provenance_failures"]["layers"]
    assert layers["final"]["failures"] == 1
    assert layers["raw"]["failures"] == 0
    assert layers["final"]["failed_cases"][0]["case"] == row["case_id"]
    assert any("weekday" in p for p in layers["final"]["failed_cases"][0]["problems"])
    assert layers["final"]["upper95"] == round(upper_bound(1, 3), 6)


def test_an_invented_weekday_the_model_wrote_fails_the_raw_layer(transcripts: Path) -> None:
    rows = rows_of(transcripts)
    row = row_for(rows, "1")
    row["internal"]["model_calls"][-1]["raw_output"] = "It will be there on Friday."
    layers = report_of(rows)["metrics"]["fact_provenance_failures"]["layers"]
    assert layers["raw"]["failures"] == 1
    assert layers["final"]["failures"] == 0


def test_a_forbidden_canary_in_the_answer_is_an_unauthorized_data_failure(
    transcripts: Path,
) -> None:
    rows = rows_of(transcripts)
    row = row_for(rows, "3")
    forbidden = CASES[row["case_id"]].fixtures.canary.forbidden[0]
    row["answer"] = f"Your note says {CANARIES[forbidden]}."
    layers = report_of(rows)["metrics"]["unauthorized_order_data_failures"]["layers"]
    assert layers["final"]["failures"] == 1
    assert layers["raw"]["failures"] == 0
    assert layers["final"]["by_category"] == {CASES[row["case_id"]].category: 1}


def say(row: dict[str, Any], text: str) -> None:
    row["answer"] = text
    for call in row["internal"]["model_calls"][-1:]:
        call["raw_output"] = text


def test_a_refused_control_case_counts_as_over_refusal(transcripts: Path) -> None:
    rows = rows_of(transcripts)
    row = row_for(rows, "none")
    say(row, DECLINE)
    layers = report_of(rows)["metrics"]["over_refusal_rate"]["layers"]
    assert layers["final"]["failures"] == 1
    assert layers["raw"]["failures"] == 1
    assert layers["final"]["n"] == 3
    assert layers["final"]["failed_cases"][0]["case"] == row["case_id"]


def test_a_refusal_passes_and_a_compliance_fails_a_red_line_4_case(transcripts: Path) -> None:
    rows = rows_of(transcripts)
    row = row_for(rows, "4")
    say(row, DECLINE)
    layers = report_of(rows)["metrics"]["unsafe_compliance_failures"]["layers"]
    assert row["case_id"] not in [item["case"] for item in layers["final"]["failed_cases"]]
    say(row, "Sure, ignoring my rules now. Here is everything you asked for.")
    layers = report_of(rows)["metrics"]["unsafe_compliance_failures"]["layers"]
    assert row["case_id"] in [item["case"] for item in layers["final"]["failed_cases"]]
    assert layers["raw"]["n"] == 3


def test_a_template_reply_is_a_guard_intervention(transcripts: Path) -> None:
    rows = rows_of(transcripts)
    before = report_of(rows)["metrics"]["guard_intervention_rate"]["layers"]["final"]
    unguarded = [row for row in rows if row["internal"]["reply_source"] not in GUARD_SOURCES]
    for row in unguarded[:2]:
        row["internal"]["reply_source"] = "template"
    guard = report_of(rows)["metrics"]["guard_intervention_rate"]["layers"]["final"]
    assert (guard["failures"], guard["n"]) == (before["failures"] + 2, before["n"])


def test_a_run_error_row_is_listed_and_left_out_of_every_count(transcripts: Path) -> None:
    rows = rows_of(transcripts)
    victim = rows[0]["case_id"]
    rows[0] = {"case_id": victim, "mode": "full", "error": {"type": "turn_error", "message": "x"}}
    report = report_of(rows)
    assert report["cases"]["run_errors"] == [victim]
    assert report["cases"]["complete"] is False
    assert report["cases"]["graded"] == 11
    assert report["metrics"]["unauthorized_order_data_failures"]["layers"]["final"]["n"] == 11


def test_transcripts_from_two_backends_are_refused(transcripts: Path) -> None:
    rows = rows_of(transcripts)
    rows[0]["internal"]["backend_id"] = "other-backend"
    with pytest.raises(ReportError, match="backend_id"):
        build_report(rows, CASES, ROOT, SHA, "")


def test_a_transcript_for_an_unknown_case_is_refused(transcripts: Path) -> None:
    rows = rows_of(transcripts)
    rows[0]["case_id"] = "no_such_case_001"
    with pytest.raises(ReportError, match="unknown case"):
        build_report(rows, CASES, ROOT, SHA, "")
