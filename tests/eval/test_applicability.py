import argparse
import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest
from fakes.agent_launch import inprocess_launcher

from gisting.eval.applicability import (
    FILE_NAME,
    POLICY_TOOL,
    REASON,
    partition_applicable,
    production_tools,
)
from gisting.eval.case_files import load_cases
from gisting.eval.case_rules import POLICY_ACTIONS
from gisting.eval.cli_grade import grade_directory
from gisting.eval.cli_run import configure_run, handle_run
from gisting.eval.report import ReportError, build_report, load_rows, with_not_applicable
from gisting.eval.runner import RunSpec, Selection, run_cases, select_cases

ROOT = Path(__file__).resolve().parents[2]
SECRET = "applicability-test-secret"
LOADED, _PROBLEMS = load_cases(ROOT)
CASES = {item.case.id: item.case for item in LOADED}
WITHOUT = frozenset({"lookup_order", "handoff_to_human"})
WITH = WITHOUT | {POLICY_TOOL}
SHA = "t" * 40


@pytest.fixture(autouse=True)
def secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GISTING_EMAIL_SECRET", SECRET)


def run_dir(tmp_path: Path, ids: tuple[str, ...]) -> Path:
    env_file = tmp_path / "empty.env"
    env_file.write_text("")
    cases = select_cases(LOADED, Selection(("dev",), red_lines=("none",), per_red_line=3))
    spec = RunSpec(
        ROOT,
        "full",
        tmp_path / "out",
        inprocess_launcher(env_file),
        env_file=env_file,
        not_applicable=ids,
    )
    run_cases(spec, cases)
    return spec.out


def test_production_tools_are_read_from_the_tool_schemas_and_lack_search_policy() -> None:
    assert POLICY_TOOL not in production_tools(ROOT)
    assert "lookup_order" in production_tools(ROOT)


def test_without_search_policy_exactly_the_forty_policy_controls_are_not_applicable() -> None:
    kept, skipped = partition_applicable(LOADED, WITHOUT)
    cases = [item.case for item in skipped]
    assert len(cases) == 40
    assert {str(case.red_line) for case in cases} == {"none"}
    assert {case.expect.scenario for case in cases} <= set(POLICY_ACTIONS)
    assert all(case.family.startswith("ctl_kb_") for case in cases)
    assert len(kept) + len(skipped) == len(LOADED)


def test_with_search_policy_nothing_is_excluded() -> None:
    kept, skipped = partition_applicable(LOADED, WITH)
    assert skipped == []
    assert len(kept) == len(LOADED)


@pytest.mark.parametrize("line", [1, 2, 3, 4])
def test_a_red_line_case_is_never_excluded_even_when_it_expects_a_policy_action(line: int) -> None:
    control = next(i for i in LOADED if i.case.expect.scenario in POLICY_ACTIONS)
    risky = dataclasses.replace(control, case=dataclasses.replace(control.case, red_line=line))
    _kept, skipped = partition_applicable([risky], WITHOUT)
    assert skipped == []


def test_every_red_line_case_of_the_committed_set_stays_selected() -> None:
    kept, _skipped = partition_applicable(LOADED, WITHOUT)
    wanted = [i for i in LOADED if str(i.case.red_line) != "none"]
    assert [i for i in kept if str(i.case.red_line) != "none"] == wanted


def test_the_run_summary_names_the_count_the_reason_and_the_ids(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    env_file = tmp_path / "empty.env"
    env_file.write_text("")
    parser = argparse.ArgumentParser()
    configure_run(parser)
    args = parser.parse_args(
        [
            "--mode",
            "full",
            "--out",
            str(tmp_path / "out"),
            "--red-line",
            "none",
            "--per-red-line",
            "3",
        ]
        + ["--env-file", str(env_file)]
    )
    assert handle_run(args, inprocess_launcher(env_file)) in (0, 1)
    summary: dict[str, Any] = json.loads(capsys.readouterr().out)
    expected = sorted(
        i.case.id for i in partition_applicable(LOADED, WITHOUT)[1] if i.case.split == "dev"
    )
    assert summary["cases"] == 3
    assert summary["not_applicable"] == {
        "count": len(expected),
        "reason": REASON,
        "case_ids": expected,
    }


def test_a_selection_made_only_of_excluded_cases_is_refused_as_empty(tmp_path: Path) -> None:
    env_file = tmp_path / "empty.env"
    env_file.write_text("")
    parser = argparse.ArgumentParser()
    configure_run(parser)
    out = tmp_path / "out"
    args = parser.parse_args([
        "--mode",
        "full",
        "--out",
        str(out),
        "--family",
        "ctl_kb_help_basics",
        "--env-file",
        str(env_file),
    ])
    assert handle_run(args, inprocess_launcher(env_file)) == 2


def test_the_report_carries_the_count_reason_and_ids(tmp_path: Path) -> None:
    ids = tuple(sorted(i.case.id for i in partition_applicable(LOADED, WITHOUT)[1]))
    out = run_dir(tmp_path, ids)
    report = grade_directory(out, ROOT, SHA)
    assert report["cases"]["not_applicable"] == {  # type: ignore[index]
        "count": 40,
        "reason": REASON,
        "case_ids": list(ids),
    }
    assert json.loads((out / "report.json").read_text())["cases"]["not_applicable"]["count"] == 40


def test_a_run_that_excluded_nothing_says_so(tmp_path: Path) -> None:
    out = run_dir(tmp_path, ())
    report = grade_directory(out, ROOT, SHA)
    assert report["cases"]["not_applicable"] == {  # type: ignore[index]
        "count": 0,
        "reason": None,
        "case_ids": [],
    }


def test_a_report_from_before_the_mechanism_has_no_field_and_still_regrades(tmp_path: Path) -> None:
    out = run_dir(tmp_path, ())
    (out / FILE_NAME).unlink()
    report = grade_directory(out, ROOT, SHA)
    assert "not_applicable" not in report["cases"]  # type: ignore[operator]


def regrade(out: Path) -> None:
    from gisting.eval.applicability import read_record

    text = (out / "transcripts.jsonl").read_text(encoding="utf-8")
    rows = load_rows(out / "transcripts.jsonl")
    with_not_applicable(build_report(rows, CASES, ROOT, SHA, text), read_record(out), rows, CASES)


def test_a_record_that_hides_a_red_line_case_is_refused(tmp_path: Path) -> None:
    red = next(i.case.id for i in LOADED if str(i.case.red_line) == "3")
    out = run_dir(tmp_path, ())
    (out / FILE_NAME).write_text(json.dumps({"reason": REASON, "case_ids": [red]}))
    with pytest.raises(ReportError, match="not applicable"):
        regrade(out)


def test_a_record_that_hides_a_case_which_has_a_transcript_is_refused(tmp_path: Path) -> None:
    out = run_dir(tmp_path, ())
    answered = json.loads((out / "transcripts.jsonl").read_text().splitlines()[0])["case_id"]
    (out / FILE_NAME).write_text(json.dumps({"reason": REASON, "case_ids": [answered]}))
    with pytest.raises(ReportError, match="not applicable"):
        regrade(out)


def test_a_record_with_an_unknown_reason_is_refused(tmp_path: Path) -> None:
    ids = [i.case.id for i in partition_applicable(LOADED, WITHOUT)[1]][:1]
    out = run_dir(tmp_path, ())
    (out / FILE_NAME).write_text(json.dumps({"reason": "because", "case_ids": ids}))
    with pytest.raises(ReportError, match="not applicable"):
        regrade(out)
