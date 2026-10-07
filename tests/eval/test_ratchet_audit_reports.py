from pathlib import Path

import pytest
from audit_support import (
    BASELINE,
    Lab,
    baseline_text,
    culprits,
    epoch,
    messages,
    new_lab,
    report_files,
    run,
    tree_name,
)


@pytest.fixture
def lab(tmp_path: Path) -> Lab:
    return new_lab(tmp_path)


def test_modified_and_deleted_reports_fail(lab: Lab) -> None:
    lab.genesis()
    lab.commit(report_files(1))
    edited = lab.commit({name: text + " " for name, text in report_files(1).items()})
    result = run(lab)
    assert culprits(result) == {edited}
    assert "was modified" in messages(result)
    lab.commit({name: None for name in report_files(1)})
    assert "was deleted" in messages(run(lab))


def test_a_file_added_to_an_existing_report_fails(lab: Lab) -> None:
    lab.genesis()
    lab.commit(report_files(1))
    bad = lab.commit({f"eval/reports/{tree_name(1)}/full/extra.txt": "x"})
    result = run(lab)
    assert culprits(result) == {bad}
    assert "existing report" in messages(result)


def test_a_stray_file_under_the_reports_directory_fails(lab: Lab) -> None:
    lab.genesis()
    bad = lab.commit({"eval/reports/notes.txt": "x"})
    result = run(lab)
    assert culprits(result) == {bad}
    assert "is not shaped like" in messages(result)
    assert result.reports == 0


def test_reports_present_at_the_anchor_may_stay_untouched(lab: Lab) -> None:
    lab.genesis(report_files(1, rate=0.9))
    lab.commit({"notes.txt": "x"})
    assert run(lab).findings == ()


def test_a_new_report_with_a_redline_failure_fails(lab: Lab) -> None:
    lab.genesis()
    bad = lab.commit(report_files(1, red=0.01))
    result = run(lab)
    assert culprits(result) == {bad}
    assert "redline_failures" in messages(result)


def test_a_new_report_worse_than_the_parent_baseline_fails(lab: Lab) -> None:
    lab.genesis()
    bad = lab.commit(report_files(1, rate=0.21))
    result = run(lab)
    assert culprits(result) == {bad}
    assert "regressed" in messages(result)


def test_a_new_report_equal_to_the_baseline_passes(lab: Lab) -> None:
    lab.genesis()
    lab.commit(report_files(1))
    assert run(lab).findings == ()


def test_a_new_report_of_a_new_epoch_is_judged_on_its_redlines_only(lab: Lab) -> None:
    lab.genesis()
    lab.commit(report_files(1, rules="fresh", rate=0.9))
    lab.commit(report_files(2, "gist", rules="fresh", red=0.01))
    text = messages(run(lab))
    assert "regressed" not in text
    assert text.count("redline_failures") == 1
    assert text.count("has no baseline") == 2


def test_a_new_report_is_judged_against_the_parent_baseline_not_the_one_it_ships_with(
    tmp_path: Path, lab: Lab
) -> None:
    lab.genesis()
    bad = lab.signed_commit({BASELINE: baseline_text(epoch(rate=0.3)), **report_files(1, rate=0.3)})
    result = run(lab)
    assert culprits(result) == {bad}
    assert "regressed" in messages(result)


def test_a_new_report_that_cannot_be_loaded_fails(lab: Lab) -> None:
    lab.genesis()
    bad = lab.commit(report_files(1, identity_ok=False))
    result = run(lab)
    assert culprits(result) == {bad}
    assert "cannot be judged" in messages(result)


def test_a_new_report_cannot_be_judged_without_a_parent_baseline(lab: Lab) -> None:
    lab.genesis()
    lab.signed_commit({BASELINE: None})
    lab.commit(report_files(1))
    assert "cannot judge the new reports" in messages(run(lab))
