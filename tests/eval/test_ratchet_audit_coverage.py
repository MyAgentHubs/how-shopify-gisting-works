import json
from collections.abc import Mapping
from pathlib import Path

import pytest
from audit_support import (
    CASE_IDS,
    CASES_FILE,
    Lab,
    culprits,
    messages,
    new_lab,
    report_files,
    run,
    tree_name,
)
from waiver_support import waiver_commit

POLICY_CASE = {"id": "ctl_policy", "red_line": "none", "expect": {"scenario": "policy_answer"}}
PLAIN_CONTROL = {"id": "ctl_plain", "red_line": "none", "expect": {"scenario": "reply"}}
REASON = "search_policy not in production tools"
BASE = f"eval/reports/{tree_name(1)}/full"


@pytest.fixture
def lab(tmp_path: Path) -> Lab:
    return new_lab(tmp_path)


def rows_text(*ids: str) -> str:
    return "".join(json.dumps({"case_id": case}) + "\n" for case in ids)


def with_rows(*ids: str) -> dict[str, str]:
    return {**report_files(1), f"{BASE}/transcripts.jsonl": rows_text(*ids)}


def with_cases(*extra: Mapping[str, object]) -> dict[str, str | None]:
    lines = [{"id": case, "red_line": 1, "expect": {"scenario": "ask"}} for case in CASE_IDS]
    return {CASES_FILE: "".join(json.dumps(line) + "\n" for line in [*lines, *extra])}


def test_a_report_that_skips_a_case_is_a_finding(lab: Lab) -> None:
    lab.genesis()
    bad = lab.commit(with_rows(*CASE_IDS[:-1]))
    result = run(lab)
    assert culprits(result) == {bad}
    assert "1 cases of the declared splits have no row (case_c)" in messages(result)


def test_a_report_with_a_row_for_an_unknown_case_is_a_finding(lab: Lab) -> None:
    lab.genesis()
    lab.commit(with_rows(*CASE_IDS, "invented"))
    assert "1 rows are outside the declared splits (invented)" in messages(run(lab))


def test_a_report_with_a_repeated_row_is_a_finding(lab: Lab) -> None:
    lab.genesis()
    lab.commit(with_rows(*CASE_IDS, CASE_IDS[0]))
    assert "1 cases have more than one row (case_a)" in messages(run(lab))


def test_a_report_that_declares_no_splits_is_a_finding(lab: Lab) -> None:
    lab.genesis()
    files = report_files(1)
    document = json.loads(files[f"{BASE}/report.json"])
    del document["cases"]
    lab.commit({**files, f"{BASE}/report.json": json.dumps(document)})
    assert "the report declares no splits" in messages(run(lab))


def test_a_case_left_out_as_not_applicable_is_not_missing(lab: Lab) -> None:
    lab.genesis(with_cases(POLICY_CASE))
    record = {"case_ids": ["ctl_policy"], "reason": REASON}
    lab.commit({**with_rows(*CASE_IDS), f"{BASE}/not_applicable.json": json.dumps(record)})
    assert run(lab).findings == ()


def test_a_policy_case_without_a_not_applicable_record_is_missing(lab: Lab) -> None:
    lab.genesis(with_cases(POLICY_CASE))
    lab.commit(with_rows(*CASE_IDS))
    assert "no row (ctl_policy)" in messages(run(lab))


def test_a_case_that_cannot_be_left_out_is_not_excused_by_the_record(lab: Lab) -> None:
    lab.genesis(with_cases(POLICY_CASE, PLAIN_CONTROL))
    record = {"case_ids": ["case_c", "ctl_plain", "ctl_policy"], "reason": REASON}
    lab.commit({**with_rows(*CASE_IDS[:-1]), f"{BASE}/not_applicable.json": json.dumps(record)})
    text = messages(run(lab))
    assert "not applicable cases cannot be left out" in text
    assert "case_c" in text


def test_a_not_applicable_case_that_has_a_row_is_a_finding(lab: Lab) -> None:
    lab.genesis(with_cases(POLICY_CASE))
    record = {"case_ids": ["ctl_policy"], "reason": REASON}
    files = {
        **with_rows(*CASE_IDS, "ctl_policy"),
        f"{BASE}/not_applicable.json": json.dumps(record),
    }
    lab.commit(files)
    assert "left out as not applicable have rows" in messages(run(lab))


def test_a_report_may_cover_the_cases_of_its_own_commit_when_cases_grow_later(lab: Lab) -> None:
    lab.genesis()
    lab.commit(report_files(1))
    lab.commit(with_cases({"id": "later", "red_line": 1, "expect": {"scenario": "ask"}}))
    assert run(lab).findings == ()


def test_a_not_applicable_record_that_repeats_an_id_is_a_finding(lab: Lab) -> None:
    lab.genesis(with_cases(POLICY_CASE))
    record = {"case_ids": ["ctl_policy", "ctl_policy"], "reason": REASON}
    lab.commit({**with_rows(*CASE_IDS), f"{BASE}/not_applicable.json": json.dumps(record)})
    assert "not applicable ids repeat" in messages(run(lab))


def test_a_report_of_one_split_does_not_owe_the_cases_of_the_other(lab: Lab) -> None:
    train = {"id": "train_case", "red_line": 1, "expect": {"scenario": "ask"}}
    lab.genesis({"eval/cases/train/family.jsonl": json.dumps(train) + "\n"})
    lab.commit(report_files(1))
    assert run(lab).findings == ()


def test_a_partial_report_is_let_in_only_by_a_signed_waiver(lab: Lab) -> None:
    lab.genesis()
    files = with_rows(*CASE_IDS[:-1])
    signed = waiver_commit(lab, files, list(files))
    result = run(lab)
    assert result.findings == ()
    assert [item.commit for item in result.waivers] == [signed]
    assert "have no row" in result.waivers[0].message
