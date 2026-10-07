from pathlib import Path

import pytest
from audit_support import (
    BASE_FILES,
    BASELINE,
    Lab,
    baseline_text,
    epoch,
    fake_loader,
    new_lab,
    report_files,
)
from guard_support import allow, git

from gisting.eval.cli import main
from gisting.eval.guard_git import EMPTY_SNAPSHOT, change_between, index_snapshot, tree_snapshot
from gisting.eval.guard_preview import preview_lines
from gisting.eval.ratchet_audit_reports import ReportLoader
from gisting.eval.ratchet_audit_tree import Tree

KEY = "backend-one/rules-one/full"


@pytest.fixture
def lab(tmp_path: Path) -> Lab:
    lab = new_lab(tmp_path)
    lab.genesis()
    return lab


def preview(lab: Lab) -> list[str]:
    parent = Tree(lab.root, tree_snapshot(lab.root, "HEAD"))
    new = Tree(lab.root, index_snapshot(lab.root))
    change = change_between(lab.root, parent.snapshot, new.snapshot)
    return preview_lines(ReportLoader(fake_loader), parent, new, change)


def test_a_loosening_is_shown_with_its_reason_and_the_value_change(lab: Lab) -> None:
    lab.stage({BASELINE: baseline_text(epoch(rate=0.3))})
    lines = preview(lab)
    assert "baseline classification: NeedsSignature" in lines
    assert any(line.startswith("  reason:") and "got worse: 0.2 -> 0.3" in line for line in lines)
    assert f"  {KEY} rate: 0.2 -> 0.3 (ratchet, down is better)" in lines
    assert "signature required: yes" in lines


def test_a_tightening_with_its_report_says_that_the_audit_would_not_need_a_signature(
    lab: Lab,
) -> None:
    lab.stage({BASELINE: baseline_text(epoch(rate=0.15)), **report_files(1, rate=0.15)})
    lines = preview(lab)
    assert any(line.startswith("baseline classification: Tighten") for line in lines)
    assert f"  {KEY} rate: 0.2 -> 0.15 (ratchet, down is better)" in lines
    assert "signature required: no" in lines


def test_a_baseline_change_next_to_another_protected_file_still_needs_a_signature(
    lab: Lab,
) -> None:
    lab.stage({
        BASELINE: baseline_text(epoch(rate=0.15)),
        **report_files(1, rate=0.15),
        "eval/metrics.toml": BASE_FILES["eval/metrics.toml"] + "\n",
    })
    lines = preview(lab)
    assert "signature required: yes" in lines
    assert any("eval/metrics.toml" in line for line in lines)


def test_a_change_that_leaves_the_baseline_alone_says_so(lab: Lab) -> None:
    lab.stage({"scripts/check_eval_ratchet.py": "pass  \n"})
    lines = preview(lab)
    assert "baseline classification: Unchanged" in lines
    assert "signature required: yes" in lines


def test_the_genesis_preview_lists_the_baseline_values_it_anchors(tmp_path: Path) -> None:
    lab = new_lab(tmp_path)
    lab.stage({BASELINE: baseline_text(), **BASE_FILES})
    allow(lab.root, lab.key)
    git(lab.root, "add", "--", ".github/allowed_signers")
    parent = Tree(lab.root, EMPTY_SNAPSHOT)
    new = Tree(lab.root, index_snapshot(lab.root))
    change = change_between(lab.root, parent.snapshot, new.snapshot)
    lines = preview_lines(ReportLoader(fake_loader), parent, new, change)
    assert "baseline classification: not applicable, the anchor has no parent state" in lines
    assert f"  {KEY} rate = 0.2" in lines
    assert "signature required: yes" in lines


def test_the_cli_prints_the_preview_between_the_paths_and_the_commands(
    tmp_path: Path, lab: Lab, capsys: pytest.CaptureFixture[str]
) -> None:
    lab.stage({BASELINE: baseline_text(epoch(rate=0.3))})
    assert main(["guard-hash", "--root", str(lab.root), "--out", str(tmp_path / "m.msg")]) == 0
    lines = capsys.readouterr().out.splitlines()
    paths_at = lines.index("protected paths changed:")
    classification_at = lines.index("baseline classification: NeedsSignature")
    commands_at = lines.index("run these two commands from the repository root:")
    assert paths_at < classification_at < commands_at


def test_the_default_message_name_carries_the_hash(
    tmp_path: Path,
    lab: Lab,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("tempfile.tempdir", str(tmp_path))
    lab.stage({BASELINE: baseline_text(epoch(rate=0.3))})
    assert main(["guard-hash", "--root", str(lab.root)]) == 0
    digest = capsys.readouterr().out.splitlines()[0].removeprefix("guard hash: ")
    assert (tmp_path / f"gisting-guard-{digest[:12]}.msg").is_file()
