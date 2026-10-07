from pathlib import Path

import pytest
from guard_support import (
    GUARD_FILE,
    PATTERNS,
    commit_all,
    git,
    guard_text,
    new_repo,
    sha,
    write,
)

from gisting.eval.guard_git import (
    GENESIS_REQUIRED,
    GuardChange,
    change_between,
    genesis_gaps,
    staged_change,
    staged_genesis_change,
    tree_snapshot,
)
from gisting.eval.guard_signature import EMPTY_TREE, File, GuardError, diff_hash

MODE = "100644"


def commit_change(root: Path, parent: str, new: str) -> GuardChange:
    return change_between(root, tree_snapshot(root, parent), tree_snapshot(root, new))


def test_staged_change_reads_head_against_the_index(tmp_path: Path) -> None:
    root = new_repo(tmp_path / "r", {"eval/baseline.json": "old", "README.md": "a"})
    write(root, {"eval/baseline.json": "new", "README.md": "b"})
    git(root, "add", "--", "eval/baseline.json", "README.md")
    write(root, {"eval/baseline.json": "unstaged"})
    change = staged_change(root)
    expected = sha("\0".join(["eval/baseline.json", MODE, sha("old"), MODE, sha("new")]) + "\n")
    assert change.paths == ("eval/baseline.json",)
    assert change.digest == expected
    assert change.parent_tree == git(root, "rev-parse", "HEAD^{tree}")


def test_staged_change_with_only_unrelated_files_is_empty(tmp_path: Path) -> None:
    root = new_repo(tmp_path / "r", {"README.md": "a"})
    write(root, {"README.md": "b", "notes.txt": "n"})
    git(root, "add", "--", "README.md", "notes.txt")
    change = staged_change(root)
    assert change.paths == ()
    assert change.digest == sha("")


def test_staged_change_sees_an_added_and_a_deleted_protected_file(tmp_path: Path) -> None:
    root = new_repo(tmp_path / "r", {"eval/baseline.json": "old"})
    git(root, "rm", "-q", "--", "eval/baseline.json")
    write(root, {"src/gisting/eval/baseline_diff.py": "x"})
    git(root, "add", "--", "src/gisting/eval/baseline_diff.py")
    change = staged_change(root)
    assert change.paths == ("eval/baseline.json", "src/gisting/eval/baseline_diff.py")
    assert change.digest == diff_hash(
        PATTERNS,
        {"eval/baseline.json": File(MODE, b"old")},
        {"src/gisting/eval/baseline_diff.py": File(MODE, b"x")},
    )


def test_commit_change_is_stable_across_different_histories(tmp_path: Path) -> None:
    first = new_repo(tmp_path / "a", {"eval/baseline.json": "old"})
    commit_all(first, {"README.md": "noise"})
    commit_all(first, {"eval/baseline.json": "new"})
    second = new_repo(tmp_path / "b", {"eval/baseline.json": "old"})
    commit_all(second, {"eval/baseline.json": "new", "other.txt": "different history"})
    one = commit_change(first, "HEAD~1", "HEAD")
    two = commit_change(second, "HEAD~1", "HEAD")
    assert one.digest == two.digest
    assert one.paths == two.paths == ("eval/baseline.json",)


def test_staged_change_matches_the_commit_it_becomes(tmp_path: Path) -> None:
    root = new_repo(tmp_path / "r", {"eval/baseline.json": "old"})
    write(root, {"eval/baseline.json": "new"})
    git(root, "add", "--", "eval/baseline.json")
    staged = staged_change(root)
    git(root, "commit", "-q", "-m", "change")
    assert commit_change(root, "HEAD~1", "HEAD") == staged


def test_a_pattern_added_by_the_change_still_protects_the_new_file(tmp_path: Path) -> None:
    root = new_repo(tmp_path / "r", {"eval/baseline.json": "same"})
    write(root, {GUARD_FILE: guard_text([*PATTERNS, "extra/*.txt"]), "extra/a.txt": "x"})
    git(root, "add", "--", GUARD_FILE, "extra/a.txt")
    assert staged_change(root).paths == (GUARD_FILE, "extra/a.txt")


def test_a_pattern_removed_by_the_change_still_protects_the_old_file(tmp_path: Path) -> None:
    root = new_repo(tmp_path / "r", {"eval/baseline.json": "old"})
    write(root, {GUARD_FILE: guard_text([GUARD_FILE]), "eval/baseline.json": "new"})
    git(root, "add", "--", GUARD_FILE, "eval/baseline.json")
    assert staged_change(root).paths == (GUARD_FILE, "eval/baseline.json")


def test_a_repository_without_a_guard_file_is_refused(tmp_path: Path) -> None:
    root = tmp_path / "r"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    write(root, {"README.md": "a"})
    git(root, "add", "--", "README.md")
    git(root, "commit", "-q", "-m", "init")
    with pytest.raises(GuardError, match="guard.json"):
        staged_change(root)


def test_an_unknown_revision_is_refused(tmp_path: Path) -> None:
    root = new_repo(tmp_path / "r", {"eval/baseline.json": "old"})
    with pytest.raises(GuardError, match="git"):
        commit_change(root, "no-such-rev", "HEAD")


def test_staged_genesis_change_hashes_unchanged_tracked_files_against_nothing(
    tmp_path: Path,
) -> None:
    root = new_repo(tmp_path / "r", {"eval/baseline.json": "same", "README.md": "a"})
    change = staged_genesis_change(root)
    assert change.paths == (GUARD_FILE, "eval/baseline.json")
    assert change.digest == diff_hash(
        PATTERNS,
        {},
        {GUARD_FILE: File(MODE, guard_text().encode()), "eval/baseline.json": File(MODE, b"same")},
    )
    assert change.digest != staged_change(root).digest
    assert change.parent_tree == EMPTY_TREE


def test_a_chmod_alone_is_a_protected_change_with_its_own_hash(tmp_path: Path) -> None:
    root = new_repo(tmp_path / "r", {"eval/baseline.json": "same"})
    git(root, "update-index", "--chmod=+x", "eval/baseline.json")
    executable = staged_change(root)
    assert executable.paths == ("eval/baseline.json",)
    git(root, "update-index", "--chmod=-x", "eval/baseline.json")
    assert staged_change(root).paths == ()
    assert executable.digest != staged_change(root).digest


def test_swapping_a_protected_file_for_a_symlink_with_the_same_bytes_changes_the_hash(
    tmp_path: Path,
) -> None:
    root = new_repo(tmp_path / "r", {"eval/baseline.json": "target"})
    blob = git(root, "rev-parse", "HEAD:eval/baseline.json")
    git(root, "update-index", "--cacheinfo", f"120000,{blob},eval/baseline.json")
    change = staged_change(root)
    assert change.paths == ("eval/baseline.json",)
    git(root, "update-index", "--cacheinfo", f"100755,{blob},eval/baseline.json")
    assert staged_change(root).digest != change.digest


def test_the_parent_tree_follows_the_commit_the_change_is_made_on(tmp_path: Path) -> None:
    root = new_repo(tmp_path / "r", {"eval/baseline.json": "old"})
    first = git(root, "rev-parse", "HEAD^{tree}")
    commit_all(root, {"README.md": "noise"})
    write(root, {"eval/baseline.json": "new"})
    git(root, "add", "--", "eval/baseline.json")
    assert staged_change(root).parent_tree == git(root, "rev-parse", "HEAD^{tree}") != first


def test_the_genesis_gaps_name_the_anchor_files_that_a_protected_set_leaves_out() -> None:
    assert genesis_gaps(GENESIS_REQUIRED) == []
    assert genesis_gaps(GENESIS_REQUIRED[1:]) == [GENESIS_REQUIRED[0]]
    assert genesis_gaps(()) == list(GENESIS_REQUIRED)
