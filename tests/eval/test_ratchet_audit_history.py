from pathlib import Path

import pytest
from audit_support import Lab, culprits, fake_loader, messages, new_lab, other_key, run
from guard_support import git

from gisting.eval.guard_signature import GuardError
from gisting.eval.ratchet_audit import audit
from gisting.eval.ratchet_audit_history import load_history

GENESIS = "eval/genesis.json"


@pytest.fixture
def lab(tmp_path: Path) -> Lab:
    return new_lab(tmp_path)


def swallow_the_anchored_main(lab: Lab, before_anchor: str) -> None:
    git(lab.root, "checkout", "-q", "-b", "rewrite", before_anchor)
    lab.commit({"rewrite.txt": "x"}, "fresh start")
    git(lab.root, "merge", "-q", "-s", "ours", "main", "-m", "swallow main")


def test_a_linear_history_after_the_anchor_passes(lab: Lab) -> None:
    lab.genesis()
    lab.commit({"a.txt": "1"})
    lab.commit({"a.txt": "2"})
    result = run(lab)
    assert (result.commits, result.findings) == (2, ())


def test_a_merge_commit_after_the_anchor_is_a_finding_even_when_it_changes_nothing(
    lab: Lab,
) -> None:
    lab.genesis()
    git(lab.root, "checkout", "-q", "-b", "side")
    lab.commit({"side.txt": "x"}, "side")
    git(lab.root, "checkout", "-q", "main")
    lab.commit({"notes.txt": "x"})
    git(lab.root, "merge", "-q", "--no-ff", "side", "-m", "merge")
    result = run(lab)
    assert culprits(result) == {lab.head()}
    assert "2 parents" in messages(result)


def test_a_signed_change_merged_from_a_side_branch_is_still_a_finding(lab: Lab) -> None:
    lab.genesis()
    git(lab.root, "checkout", "-q", "-b", "side")
    lab.signed_commit({"eval/metrics.toml": "# edited\n"})
    git(lab.root, "checkout", "-q", "main")
    lab.commit({"notes.txt": "x"})
    git(lab.root, "merge", "-q", "--no-ff", "side", "-m", "merge")
    assert "2 parents" in messages(run(lab))


def test_swallowing_the_anchored_main_with_an_ours_merge_loses_the_anchor_loudly(
    lab: Lab,
) -> None:
    before = lab.head()
    genesis = lab.genesis()
    lab.commit({"notes.txt": "x"})
    swallow_the_anchored_main(lab, before)
    result = run(lab)
    assert result.anchor is None
    assert culprits(result) == {genesis}
    assert "first-parent chain" in messages(result)


def test_swallowing_main_and_building_a_second_genesis_is_a_finding(
    tmp_path: Path, lab: Lab
) -> None:
    before = lab.head()
    first = lab.genesis()
    lab.commit({"notes.txt": "x"})
    swallow_the_anchored_main(lab, before)
    rogue = Lab(lab.root, other_key(tmp_path))
    second = rogue.genesis()
    result = run(rogue)
    assert result.anchor == second
    assert culprits(result) == {second}
    assert first[:12] in messages(result)
    assert "only once" in messages(result)


def test_a_second_genesis_introduction_on_the_first_parent_chain_is_a_finding(lab: Lab) -> None:
    first = lab.genesis()
    lab.signed_commit({GENESIS: None})
    again = lab.signed_commit({GENESIS: '{"version": 2}\n'})
    result = run(lab)
    assert result.anchor == first
    assert culprits(result) == {again}


def test_a_merge_that_brings_the_genesis_in_from_a_side_branch_is_no_anchor(lab: Lab) -> None:
    before = lab.head()
    git(lab.root, "checkout", "-q", "-b", "side", before)
    lab.genesis()
    git(lab.root, "checkout", "-q", "main")
    lab.commit({"notes.txt": "x"})
    git(lab.root, "merge", "-q", "--no-ff", "side", "-m", "merge side")
    result = run(lab)
    assert result.anchor is None
    assert "first-parent chain" in messages(result)


def test_the_history_reads_every_parent_not_only_the_first(lab: Lab) -> None:
    before = lab.head()
    genesis = lab.genesis()
    lab.commit({"notes.txt": "x"})
    swallow_the_anchored_main(lab, before)
    history = load_history(lab.root)
    assert history.introducers == (genesis,)
    assert genesis not in history.chain


def test_a_base_on_the_first_parent_chain_passes(lab: Lab) -> None:
    lab.genesis()
    tip = lab.commit({"notes.txt": "1"})
    lab.commit({"notes.txt": "2"})
    assert audit(lab.root, fake_loader, tip).findings == ()


def test_the_head_itself_is_a_valid_base(lab: Lab) -> None:
    lab.genesis()
    assert audit(lab.root, fake_loader, lab.head()).findings == ()


def test_a_base_that_the_history_swallowed_into_a_second_parent_fails(lab: Lab) -> None:
    before = lab.head()
    lab.genesis()
    tip = lab.commit({"notes.txt": "x"})
    swallow_the_anchored_main(lab, before)
    result = audit(lab.root, fake_loader, tip)
    assert "not on the first-parent chain" in messages(result)


def test_a_base_from_a_rewritten_history_fails(lab: Lab) -> None:
    lab.genesis()
    old_tip = lab.commit({"notes.txt": "old"})
    git(lab.root, "checkout", "-q", "-b", "rewrite", "main~1")
    lab.commit({"notes.txt": "rewritten"})
    result = audit(lab.root, fake_loader, old_tip)
    assert culprits(result) == {lab.head()}
    assert "not on the first-parent chain" in messages(result)


def test_a_base_that_is_not_a_commit_here_fails(lab: Lab) -> None:
    lab.genesis()
    result = audit(lab.root, fake_loader, "a" * 40)
    assert "not a commit" in messages(result)


@pytest.mark.parametrize("bad", ["--output=x", "HEAD", "main", "-1", ""])
def test_a_base_that_is_not_a_sha_is_refused(lab: Lab, bad: str) -> None:
    lab.genesis()
    with pytest.raises(GuardError, match="sha"):
        audit(lab.root, fake_loader, bad)
