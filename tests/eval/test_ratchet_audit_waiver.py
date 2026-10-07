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
    other_key,
    report_files,
    run,
)
from waiver_support import waiver_change, waiver_commit


@pytest.fixture
def lab(tmp_path: Path) -> Lab:
    return new_lab(tmp_path)


def test_a_red_report_signed_over_its_files_is_let_in_and_listed_as_a_waiver(lab: Lab) -> None:
    lab.genesis()
    files = report_files(1, red=0.01)
    signed = waiver_commit(lab, files, list(files))
    result = run(lab)
    assert result.findings == ()
    assert [item.commit for item in result.waivers] == [signed]
    assert "redline_failures" in result.waivers[0].message


def test_a_red_report_without_a_signature_is_a_finding_and_no_waiver(lab: Lab) -> None:
    lab.genesis()
    bad = lab.commit(report_files(1, red=0.01))
    result = run(lab)
    assert culprits(result) == {bad}
    assert "redline_failures" in messages(result)
    assert result.waivers == ()


def test_a_green_report_needs_no_signature_and_lists_no_waiver(lab: Lab) -> None:
    lab.genesis()
    lab.commit(report_files(1))
    result = run(lab)
    assert (result.findings, result.waivers) == ((), ())


def test_a_signature_over_the_guard_hash_alone_does_not_cover_a_red_report(lab: Lab) -> None:
    lab.genesis()
    bad = lab.signed_commit(report_files(1, red=0.01))
    result = run(lab)
    assert culprits(result) == {bad}
    assert "redline_failures" in messages(result)
    assert result.waivers == ()


def test_a_signature_of_another_key_does_not_waive_a_red_report(tmp_path: Path, lab: Lab) -> None:
    lab.genesis()
    files = report_files(1, red=0.01)
    bad = waiver_commit(lab, files, list(files), other_key(tmp_path))
    result = run(lab)
    assert culprits(result) == {bad}
    assert "not a valid signature" in messages(result)
    assert result.waivers == ()


def test_a_waiver_covers_only_the_report_it_was_signed_for(lab: Lab) -> None:
    lab.genesis()
    first = report_files(1, red=0.01)
    waiver_commit(lab, first, list(first))
    bad = lab.commit(report_files(2, red=0.01))
    result = run(lab)
    assert culprits(result) == {bad}
    assert len(result.waivers) == 1


def test_a_waiver_signed_for_changed_report_content_does_not_hold(lab: Lab) -> None:
    lab.genesis()
    signed_for = report_files(1, red=0.01)
    lab.sign_staged(waiver_change(lab, signed_for, list(signed_for)))
    lab.stage({name: text + " " for name, text in signed_for.items()})
    bad = lab.commit({})
    result = run(lab)
    assert culprits(result) == {bad}
    assert result.waivers == ()


def test_a_report_that_cannot_be_loaded_is_never_waived(lab: Lab) -> None:
    lab.genesis()
    files = report_files(1, identity_ok=False)
    bad = waiver_commit(lab, files, list(files))
    result = run(lab)
    assert culprits(result) == {bad}
    assert "cannot be judged" in messages(result)
    assert result.waivers == ()


def test_a_regressed_report_is_waived_by_the_same_signature(lab: Lab) -> None:
    lab.genesis()
    files = report_files(1, rate=0.21)
    waiver_commit(lab, files, list(files))
    result = run(lab)
    assert result.findings == ()
    assert "regressed" in result.waivers[0].message


def test_a_waiver_does_not_loosen_the_baseline_for_the_next_report(lab: Lab) -> None:
    lab.genesis()
    files = report_files(1, rate=0.21)
    waiver_commit(lab, files, list(files))
    bad = lab.commit(report_files(2, rate=0.21))
    result = run(lab)
    assert culprits(result) == {bad}
    assert "regressed" in messages(result)


def test_a_waiver_and_a_signed_baseline_change_share_one_signature(lab: Lab) -> None:
    lab.genesis()
    files = report_files(1, rate=0.21)
    both = {BASELINE: baseline_text(epoch(rate=0.21)), **files}
    waiver_commit(lab, both, list(files))
    result = run(lab)
    assert result.findings == ()
    assert len(result.waivers) == 1
