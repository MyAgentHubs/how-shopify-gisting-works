from pathlib import Path

import pytest
from audit_support import Lab, culprits, messages, new_lab, run
from guard_support import git

from gisting.eval.guard_git import staged_change, tree_snapshot
from gisting.eval.guard_signature import GuardError, path_problems

PATTERNS = ("eval/baseline.json", "src/gisting/eval/guard_*.py")
BAD_BYTE_PATH = "eval/bad-\udcff.txt"
OTHER_BAD_BYTE_PATH = "eval/bad-\udcfe.txt"


@pytest.fixture
def lab(tmp_path: Path) -> Lab:
    return new_lab(tmp_path)


def add_without_a_file(lab: Lab, *names: str) -> None:
    blob = git(lab.root, "rev-parse", "HEAD:README.md")
    for name in names:
        git(lab.root, "update-index", "--add", "--cacheinfo", f"100644,{blob},{name}")


def test_valid_names_and_unrelated_case_variants_are_fine() -> None:
    names = ["eval/baseline.json", "Notes.txt", "notes.txt", "src/gisting/eval/guard_git.py"]
    assert path_problems(PATTERNS, names) == []


@pytest.mark.parametrize(
    "name", ["Eval/baseline.json", "eval/Baseline.json", "SRC/gisting/eval/guard_git.py"]
)
def test_a_case_variant_of_a_protected_path_is_a_problem(name: str) -> None:
    problems = path_problems(PATTERNS, ["eval/baseline.json", name])
    assert len(problems) == 1
    assert "letter case" in problems[0]


def test_a_unicode_case_fold_of_a_protected_path_is_a_problem() -> None:
    assert path_problems(PATTERNS, ["eval/baseline.json", "eval/baseline.jſon"]) != []


def test_a_name_with_bytes_that_are_not_utf_8_is_a_problem_and_prints_safely() -> None:
    problems = path_problems(PATTERNS, [BAD_BYTE_PATH, OTHER_BAD_BYTE_PATH])
    assert len(problems) == 2
    assert all("UTF-8" in problem for problem in problems)
    assert all(problem.isascii() for problem in problems)


def test_two_invalid_names_stay_distinct_keys_in_a_snapshot(lab: Lab) -> None:
    lab.genesis()
    add_without_a_file(lab, BAD_BYTE_PATH, OTHER_BAD_BYTE_PATH)
    git(lab.root, "commit", "-q", "-m", "odd")
    blobs = tree_snapshot(lab.root, "HEAD").blobs
    assert BAD_BYTE_PATH in blobs
    assert OTHER_BAD_BYTE_PATH in blobs


def test_the_staged_change_refuses_a_tree_with_an_invalid_name(lab: Lab) -> None:
    lab.genesis()
    add_without_a_file(lab, BAD_BYTE_PATH)
    with pytest.raises(GuardError, match="UTF-8"):
        staged_change(lab.root)


def test_a_commit_that_adds_an_invalid_name_is_a_finding(lab: Lab) -> None:
    lab.genesis()
    add_without_a_file(lab, BAD_BYTE_PATH)
    git(lab.root, "commit", "-q", "-m", "odd")
    result = run(lab)
    assert culprits(result) == {lab.head()}
    assert "UTF-8" in messages(result)


def test_a_case_variant_next_to_a_protected_file_is_a_finding(lab: Lab) -> None:
    lab.genesis()
    add_without_a_file(lab, "Eval/baseline.json")
    git(lab.root, "commit", "-q", "-m", "shadow")
    result = run(lab)
    assert culprits(result) == {lab.head()}
    assert "letter case" in messages(result)


def test_a_case_variant_of_an_ordinary_file_is_not_a_finding(lab: Lab) -> None:
    lab.genesis()
    lab.commit({"notes.txt": "a"})
    add_without_a_file(lab, "Notes.txt")
    git(lab.root, "commit", "-q", "-m", "ordinary")
    assert run(lab).findings == ()
