import json
from pathlib import Path
from typing import Any

import pytest
from baseline_support import (
    BAD,
    INVENTED,
    baseline,
    make_root,
    make_run,
    refused_with,
    rewrite_rows,
)

from gisting.eval.cli_baseline import load_candidate
from gisting.eval.registry import load_registry
from gisting.eval.report import IncompleteRun

ERROR = {"type": "turn_error", "message": "the model server went away"}


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    return make_root(tmp_path, monkeypatch)


def failing_ids(directory: Path) -> list[str]:
    lines = (directory / "transcripts.jsonl").read_text(encoding="utf-8").splitlines()
    rows = [json.loads(line) for line in lines]
    return [row["case_id"] for row in rows if row.get("answer") == INVENTED]


def to_error_rows(rows: list[dict[str, Any]]) -> None:
    for index, row in enumerate(rows):
        if row.get("answer") == INVENTED:
            rows[index] = {"case_id": row["case_id"], "error": ERROR}


def drop_failing_rows(rows: list[dict[str, Any]]) -> None:
    rows[:] = [row for row in rows if row.get("answer") != INVENTED]


def test_failing_rows_turned_into_error_rows_are_refused_though_the_report_says_complete(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run = make_run(root, BAD, spoil=8)
    failing = failing_ids(run)
    assert len(failing) == 8
    rewrite_rows(run, to_error_rows)
    cases = json.loads((run / "report.json").read_text(encoding="utf-8"))["cases"]
    assert cases["complete"] is True
    refused_with(root, capsys, run, "error rows")
    metrics, _problems = load_registry(root / "eval" / "metrics.toml")
    with pytest.raises(IncompleteRun) as raised:
        load_candidate(run, root, metrics)
    assert (raised.value.reason, sorted(raised.value.case_ids)) == ("error_rows", sorted(failing))


def test_dropped_failing_rows_do_not_match_the_counts_the_report_claims(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run = make_run(root, BAD, spoil=8)
    rewrite_rows(run, drop_failing_rows)
    refused_with(root, capsys, run, "counts")
    assert baseline(root)["epochs"] == []


def test_a_report_that_calls_itself_incomplete_is_judged_by_its_rows_not_its_word(
    root: Path,
) -> None:
    run = make_run(root, BAD)
    path = run / "report.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document["cases"]["complete"] = False
    path.write_text(json.dumps(document), encoding="utf-8")
    metrics, _problems = load_registry(root / "eval" / "metrics.toml")
    assert load_candidate(run, root, metrics).values


def add_passing_twins(rows: list[dict[str, Any]]) -> None:
    rows.extend(
        {**row, "answer": "Happy to help."} for row in rows if row.get("answer") == INVENTED
    )


def test_a_passing_row_appended_for_a_failing_case_is_refused_even_with_counts_to_match(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run = make_run(root, BAD, spoil=8)
    rewrite_rows(run, add_passing_twins)
    path = run / "report.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document["cases"]["transcripts"] += 8
    document["cases"]["graded"] += 8
    path.write_text(json.dumps(document), encoding="utf-8")
    refused_with(root, capsys, run, "more than one row")
    metrics, _problems = load_registry(root / "eval" / "metrics.toml")
    with pytest.raises(IncompleteRun) as raised:
        load_candidate(run, root, metrics)
    assert (raised.value.reason, len(raised.value.case_ids)) == ("duplicate_rows", 8)
