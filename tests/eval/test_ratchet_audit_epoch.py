from pathlib import Path

import pytest
from audit_support import Lab, culprits, messages, new_lab, report_files, run
from waiver_support import waiver_commit


@pytest.fixture
def lab(tmp_path: Path) -> Lab:
    return new_lab(tmp_path)


def test_a_report_of_a_rules_version_the_baseline_does_not_know_needs_a_signature(
    lab: Lab,
) -> None:
    lab.genesis()
    bad = lab.commit(report_files(1, rules="renamed", rate=0.9))
    result = run(lab)
    assert culprits(result) == {bad}
    assert "has no baseline in the parent commit" in messages(result)
    assert "renamed" in messages(result)
    assert result.waivers == ()


def test_a_report_of_a_mode_the_baseline_does_not_know_needs_a_signature(lab: Lab) -> None:
    lab.genesis()
    bad = lab.commit(report_files(1, "gist"))
    assert culprits(run(lab)) == {bad}


def test_a_new_epoch_is_let_in_by_a_signed_waiver_and_listed(lab: Lab) -> None:
    lab.genesis()
    files = report_files(1, rules="fresh")
    signed = waiver_commit(lab, files, list(files))
    result = run(lab)
    assert result.findings == ()
    assert [item.commit for item in result.waivers] == [signed]
    assert "has no baseline" in result.waivers[0].message


def test_a_report_of_a_known_epoch_needs_no_signature(lab: Lab) -> None:
    lab.genesis()
    lab.commit(report_files(1))
    result = run(lab)
    assert (result.findings, result.waivers) == ((), ())
