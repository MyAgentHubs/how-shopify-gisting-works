from pathlib import Path

import pytest
from audit_support import (
    BASELINE,
    Lab,
    baseline_text,
    culprits,
    epoch,
    new_lab,
    other_key,
    report_files,
    run,
)
from guard_support import IDENTITY, NAMESPACE, git

from gisting.eval.guard_git import staged_change

SIGNERS = ".github/allowed_signers"
SCRIPT = "scripts/check_eval_ratchet.py"


@pytest.fixture
def lab(tmp_path: Path) -> Lab:
    return new_lab(tmp_path)


def signers_text(*keys: str) -> str:
    return "".join(f'{IDENTITY} namespaces="{NAMESPACE}" {line}\n' for line in keys)


def test_a_signed_signer_change_cannot_be_replayed_after_it_was_revoked(
    tmp_path: Path, lab: Lab
) -> None:
    lab.genesis()
    second = other_key(tmp_path)
    alone = signers_text(lab.key.public_line)
    both = signers_text(lab.key.public_line, second.public_line)
    lab.signed_commit({SIGNERS: both})
    lab.signed_commit({SIGNERS: alone})
    replay = lab.commit({SIGNERS: both})
    lab.signed_commit({BASELINE: baseline_text(epoch(rate=0.3))}, second)
    result = run(lab)
    assert culprits(result) == {replay}
    assert "not a valid signature" in result.findings[0].message


def test_a_loosening_signature_cannot_be_reused_after_tightening_back(lab: Lab) -> None:
    lab.genesis()
    loose = baseline_text(epoch(rate=0.3))
    lab.signed_commit({BASELINE: loose})
    lab.commit({BASELINE: baseline_text(epoch()), **report_files(1, rate=0.2)})
    assert run(lab).findings == ()
    replay = lab.commit({BASELINE: loose})
    assert culprits(run(lab)) == {replay}


def test_the_same_signed_change_on_the_tree_it_was_signed_for_still_passes(lab: Lab) -> None:
    lab.genesis()
    lab.signed_commit({BASELINE: baseline_text(epoch(rate=0.3))})
    assert run(lab).findings == ()


def test_a_signed_change_cherry_picked_onto_another_tip_needs_a_new_signature(
    tmp_path: Path, lab: Lab
) -> None:
    lab.genesis()
    lab.commit({"a.txt": "tip one"})
    git(lab.root, "checkout", "-q", "-b", "side", "HEAD~1")
    signed = lab.signed_commit({BASELINE: baseline_text(epoch(rate=0.3))})
    git(lab.root, "checkout", "-q", "main")
    git(lab.root, "cherry-pick", signed)
    assert culprits(run(lab)) == {lab.head()}


def make_executable(lab: Lab, name: str) -> None:
    git(lab.root, "update-index", "--chmod=+x", name)


def test_a_chmod_of_a_protected_file_needs_a_signature(lab: Lab) -> None:
    lab.genesis()
    make_executable(lab, SCRIPT)
    git(lab.root, "commit", "-q", "-m", "chmod")
    assert culprits(run(lab)) == {lab.head()}


def test_a_signed_chmod_of_a_protected_file_passes(lab: Lab) -> None:
    lab.genesis()
    make_executable(lab, SCRIPT)
    lab.sign_staged(staged_change(lab.root))
    git(lab.root, "commit", "-q", "-m", "chmod")
    assert run(lab).findings == ()
