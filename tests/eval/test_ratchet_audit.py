import json
from pathlib import Path

import pytest
from audit_support import (
    BASE_FILES,
    BASELINE,
    GUARD_PATTERNS,
    Lab,
    baseline_text,
    culprits,
    epoch,
    fake_loader,
    messages,
    new_lab,
    other_key,
    report_files,
    run,
)
from guard_support import IDENTITY, NAMESPACE, git

from gisting.eval.guard_signature import GuardError
from gisting.eval.ratchet_audit import audit

SIGNERS = ".github/allowed_signers"


@pytest.fixture
def lab(tmp_path: Path) -> Lab:
    return new_lab(tmp_path)


def signers_text(*keys: str) -> str:
    return "".join(f'{IDENTITY} namespaces="{NAMESPACE}" {line}\n' for line in keys)


def test_a_signed_genesis_anchors_the_audit(lab: Lab) -> None:
    genesis = lab.genesis()
    result = run(lab)
    assert (result.anchor, result.commits, result.reports) == (genesis, 0, 0)
    assert result.findings == ()


def test_a_genesis_as_the_very_first_commit_is_anchored(tmp_path: Path) -> None:
    lab = new_lab(tmp_path, with_history=False)
    genesis = lab.genesis()
    assert run(lab).anchor == genesis


def test_a_repository_without_genesis_is_not_anchored(lab: Lab) -> None:
    lab.commit({BASELINE: baseline_text()})
    result = run(lab)
    assert result.anchor is None
    assert result.findings == ()


def test_an_unsigned_genesis_fails(lab: Lab) -> None:
    genesis = lab.genesis(signed=False)
    result = run(lab)
    assert culprits(result) == {genesis}
    assert "no signature file" in messages(result)


def test_a_genesis_signed_by_a_key_it_does_not_list_fails(tmp_path: Path, lab: Lab) -> None:
    genesis = lab.genesis(signer=other_key(tmp_path))
    result = run(lab)
    assert culprits(result) == {genesis}
    assert "not a valid signature" in messages(result)


def test_a_genesis_edited_after_it_was_signed_fails(lab: Lab) -> None:
    genesis = lab.genesis(late={"scripts/check_eval_ratchet.py": "sneaky\n"})
    assert culprits(run(lab)) == {genesis}


def test_a_genesis_whose_protected_set_leaves_out_the_anchor_files_fails(lab: Lab) -> None:
    narrow = json.dumps({"paths": [item for item in GUARD_PATTERNS if item != "eval/genesis.json"]})
    genesis = lab.genesis({"data/eval/guard.json": narrow})
    result = run(lab)
    assert culprits(result) == {genesis}
    assert "eval/genesis.json" in messages(result)


def test_commits_before_the_anchor_are_not_audited(lab: Lab) -> None:
    lab.commit({BASELINE: "garbage", "eval/reports/loose.txt": "x"})
    lab.genesis()
    assert run(lab).findings == ()


def test_unrelated_commits_after_the_anchor_pass(lab: Lab) -> None:
    lab.genesis()
    lab.commit({"notes.txt": "a"})
    lab.commit({"README.md": "changed\n"})
    result = run(lab)
    assert (result.commits, result.findings) == (2, ())


def test_a_tightening_that_a_committed_report_holds_passes_without_a_signature(lab: Lab) -> None:
    lab.genesis()
    lab.commit(report_files(1, rate=0.15))
    lab.commit({BASELINE: baseline_text(epoch(rate=0.15))})
    result = run(lab)
    assert (result.commits, result.reports, result.findings) == (2, 1, ())


def test_a_tightening_may_ride_with_its_report_in_one_commit(lab: Lab) -> None:
    lab.genesis()
    lab.commit({BASELINE: baseline_text(epoch(rate=0.15)), **report_files(1, rate=0.15)})
    assert run(lab).findings == ()


def test_a_recorded_metric_follows_its_report_without_a_signature(lab: Lab) -> None:
    lab.genesis()
    lab.commit(report_files(1, tokens=120.0))
    lab.commit({BASELINE: baseline_text(epoch(tokens=120.0))})
    assert run(lab).findings == ()


def test_a_reformatted_baseline_passes_without_a_signature(lab: Lab) -> None:
    lab.genesis()
    lab.commit({BASELINE: json.dumps(json.loads(baseline_text()))})
    assert run(lab).findings == ()


def test_a_tightening_that_no_report_holds_fails(lab: Lab) -> None:
    lab.genesis()
    sneaky = lab.commit({BASELINE: baseline_text(epoch(rate=0.15))})
    result = run(lab)
    assert culprits(result) == {sneaky}
    assert "no committed report" in messages(result)


def test_a_report_that_fails_the_identity_check_is_no_source(lab: Lab) -> None:
    lab.genesis()
    lab.commit(report_files(1, identity_ok=False, rate=0.15))
    sneaky = lab.commit({BASELINE: baseline_text(epoch(rate=0.15))})
    result = run(lab)
    assert sneaky in culprits(result)
    assert "no committed report" in messages(result)


def test_a_report_of_another_epoch_is_no_source(lab: Lab) -> None:
    lab.genesis()
    lab.commit(report_files(1, rules="other-rules", rate=0.15))
    sneaky = lab.commit({BASELINE: baseline_text(epoch(rate=0.15))})
    assert sneaky in culprits(run(lab))


def test_a_loosened_baseline_fails_unsigned_and_passes_with_a_valid_signature(
    tmp_path: Path, lab: Lab
) -> None:
    lab.genesis()
    loose = baseline_text(epoch(rate=0.3))
    sneaky = lab.commit({BASELINE: loose})
    result = run(lab)
    assert culprits(result) == {sneaky}
    assert "got worse" in messages(result)
    other = new_lab(tmp_path / "second")
    other.genesis()
    other.signed_commit({BASELINE: loose})
    assert run(other).findings == ()


def test_a_loosening_signed_by_a_stranger_fails(tmp_path: Path, lab: Lab) -> None:
    lab.genesis()
    stranger = other_key(tmp_path)
    bad = lab.signed_commit({BASELINE: baseline_text(epoch(rate=0.3))}, stranger)
    assert culprits(run(lab)) == {bad}


def test_a_signature_added_later_does_not_rescue_the_earlier_commit(lab: Lab) -> None:
    lab.genesis()
    sneaky = lab.commit({BASELINE: baseline_text(epoch(rate=0.3))})
    lab.signed_commit({"README.md": "x\n"})
    assert culprits(run(lab)) == {sneaky}


def test_a_forged_new_epoch_fails_and_a_signed_one_passes(tmp_path: Path, lab: Lab) -> None:
    lab.genesis()
    forged = baseline_text(epoch(), epoch(rules="forged", rate=0.0))
    bad = lab.commit({BASELINE: forged})
    result = run(lab)
    assert culprits(result) == {bad}
    assert "is new" in messages(result)
    other = new_lab(tmp_path / "second")
    other.genesis()
    other.signed_commit({BASELINE: forged})
    assert run(other).findings == ()


def test_a_deleted_epoch_fails(lab: Lab) -> None:
    lab.genesis({BASELINE: baseline_text(epoch(), epoch("gist"))})
    bad = lab.commit({BASELINE: baseline_text(epoch())})
    result = run(lab)
    assert culprits(result) == {bad}
    assert "was deleted" in messages(result)


def test_a_deleted_baseline_file_fails(lab: Lab) -> None:
    lab.genesis()
    bad = lab.commit({BASELINE: None})
    assert culprits(run(lab)) == {bad}


def test_a_baseline_change_next_to_another_protected_change_needs_a_signature(lab: Lab) -> None:
    lab.genesis()
    lab.commit(report_files(1, rate=0.15))
    bad = lab.commit({
        BASELINE: baseline_text(epoch(rate=0.15)),
        "scripts/check_eval_ratchet.py": "pass  \n",
    })
    assert culprits(run(lab)) == {bad}


@pytest.mark.parametrize(
    "name",
    [
        "data/eval/guard.json",
        "eval/genesis.json",
        "eval/metrics.toml",
        "scripts/check_eval_ratchet.py",
    ],
)
def test_every_other_protected_file_needs_a_signature(tmp_path: Path, lab: Lab, name: str) -> None:
    lab.genesis()
    edited = {name: BASE_FILES[name] + "\n"}
    bad = lab.commit(edited)
    assert culprits(run(lab)) == {bad}
    other = new_lab(tmp_path / "second")
    other.genesis()
    other.signed_commit(edited)
    assert run(other).findings == ()


def test_a_commit_cannot_add_its_own_signer_and_sign_itself(tmp_path: Path, lab: Lab) -> None:
    lab.genesis()
    stranger = other_key(tmp_path)
    both = signers_text(lab.key.public_line, stranger.public_line)
    bad = lab.signed_commit({SIGNERS: both, BASELINE: baseline_text(epoch(rate=0.3))}, stranger)
    result = run(lab)
    assert culprits(result) == {bad}
    assert "not a valid signature" in messages(result)


def test_a_commit_cannot_replace_the_signers_with_its_own_key(tmp_path: Path, lab: Lab) -> None:
    lab.genesis()
    stranger = other_key(tmp_path)
    bad = lab.signed_commit({SIGNERS: signers_text(stranger.public_line)}, stranger)
    assert culprits(run(lab)) == {bad}


def test_the_listed_signer_can_add_a_second_signer_and_the_second_can_sign_next(
    tmp_path: Path, lab: Lab
) -> None:
    lab.genesis()
    second = other_key(tmp_path)
    both = signers_text(lab.key.public_line, second.public_line)
    lab.signed_commit({SIGNERS: both})
    lab.signed_commit({BASELINE: baseline_text(epoch(rate=0.3))}, second)
    assert run(lab).findings == ()


def test_deleting_genesis_needs_a_signature_and_the_anchor_survives_it(lab: Lab) -> None:
    genesis = lab.genesis()
    bad = lab.commit({"eval/genesis.json": None})
    result = run(lab)
    assert (result.anchor, culprits(result)) == (genesis, {bad})


def test_a_signed_deletion_of_genesis_keeps_the_audit_running(lab: Lab) -> None:
    genesis = lab.genesis()
    lab.signed_commit({"eval/genesis.json": None})
    lab.commit({BASELINE: baseline_text(epoch(rate=0.3))})
    result = run(lab)
    assert result.anchor == genesis
    assert len(result.findings) == 1


def test_a_loosening_merged_from_a_side_branch_is_caught_on_the_merge(lab: Lab) -> None:
    lab.genesis()
    git(lab.root, "checkout", "-q", "-b", "side")
    lab.commit({BASELINE: baseline_text(epoch(rate=0.3))}, "side")
    git(lab.root, "checkout", "-q", "main")
    lab.commit({"notes.txt": "x"})
    git(lab.root, "merge", "-q", "--no-ff", "side", "-m", "merge")
    result = run(lab)
    assert culprits(result) == {lab.head()}


def test_a_shallow_history_is_refused(tmp_path: Path, lab: Lab) -> None:
    lab.genesis()
    lab.commit({"notes.txt": "x"})
    clone = tmp_path / "shallow"
    git(tmp_path, "clone", "-q", "--depth", "1", f"file://{lab.root}", str(clone))
    with pytest.raises(GuardError, match="shallow"):
        audit(clone, fake_loader)


def test_a_broken_guard_file_is_a_finding_not_a_crash(lab: Lab) -> None:
    lab.genesis()
    bad = lab.commit({"data/eval/guard.json": "not json"})
    result = run(lab)
    assert culprits(result) == {bad}
    assert "guard" in messages(result)
