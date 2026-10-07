import subprocess
from pathlib import Path

import pytest

from gisting.eval.tree import GitError, code_tree_sha, dirty_paths, paths_differ

GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.com",
    "HOME": "/nonexistent",
    "PATH": "/usr/bin:/bin:/usr/local/bin",
}


def git(root: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, env=GIT_ENV, check=True
    )
    return done.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "code.py").write_text("x = 1\n")
    git(tmp_path, "add", "code.py")
    git(tmp_path, "commit", "-q", "-m", "init")
    return tmp_path


def commit_all(root: Path, name: str) -> None:
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", name)


def test_the_tree_sha_is_a_git_tree_of_the_committed_files(repo: Path) -> None:
    assert code_tree_sha(repo) == git(repo, "rev-parse", "HEAD^{tree}")


def test_committing_a_report_does_not_change_the_code_tree_sha(repo: Path) -> None:
    before = code_tree_sha(repo)
    report = repo / "eval" / "reports" / before / "full"
    report.mkdir(parents=True)
    (report / "report.json").write_text("{}\n")
    commit_all(repo, "report")
    assert git(repo, "rev-parse", "HEAD^{tree}") != before
    assert code_tree_sha(repo) == before


def test_changing_code_changes_the_code_tree_sha(repo: Path) -> None:
    before = code_tree_sha(repo)
    (repo / "code.py").write_text("x = 2\n")
    commit_all(repo, "change")
    assert code_tree_sha(repo) != before


def test_the_real_index_is_left_alone(repo: Path) -> None:
    code_tree_sha(repo)
    assert git(repo, "status", "--porcelain") == ""


def test_a_clean_tree_has_no_dirty_paths_and_reports_do_not_count(repo: Path) -> None:
    assert dirty_paths(repo) == []
    reports = repo / "eval" / "reports" / "abc"
    reports.mkdir(parents=True)
    (reports / "report.json").write_text("{}\n")
    assert dirty_paths(repo) == []


def test_modified_and_untracked_files_are_dirty(repo: Path) -> None:
    (repo / "code.py").write_text("x = 3\n")
    (repo / "new.py").write_text("y = 1\n")
    assert sorted(dirty_paths(repo)) == ["code.py", "new.py"]


def test_a_directory_that_is_not_a_repository_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(GitError):
        dirty_paths(tmp_path / "missing")


def test_paths_that_match_the_tree_do_not_differ(repo: Path) -> None:
    tree = git(repo, "rev-parse", "HEAD^{tree}")
    assert paths_differ(repo, tree, ["code.py"]) is False


def test_only_the_named_paths_decide_whether_a_tree_differs(repo: Path) -> None:
    tree = git(repo, "rev-parse", "HEAD^{tree}")
    (repo / "other.py").write_text("y = 1\n")
    commit_all(repo, "other")
    assert paths_differ(repo, tree, ["code.py"]) is False
    assert paths_differ(repo, tree, ["other.py"]) is True
    (repo / "code.py").write_text("x = 2\n")
    commit_all(repo, "change")
    assert paths_differ(repo, tree, ["code.py", "missing.py"]) is True
    assert paths_differ(repo, tree, ["."]) is True


def test_a_directory_path_covers_the_files_below_it(repo: Path) -> None:
    (repo / "tools").mkdir()
    (repo / "tools" / "a.json").write_text("{}\n")
    commit_all(repo, "tools")
    tree = git(repo, "rev-parse", "HEAD^{tree}")
    (repo / "tools" / "a.json").write_text('{"x": 1}\n')
    commit_all(repo, "edit")
    assert paths_differ(repo, tree, ["tools"]) is True


def test_a_tree_that_is_not_in_the_repository_is_an_error(repo: Path) -> None:
    with pytest.raises(GitError):
        paths_differ(repo, "0" * 40, ["code.py"])


def test_a_tree_argument_that_is_not_a_full_sha_is_refused(repo: Path) -> None:
    for text in ("HEAD", "--output=x", "abc"):
        with pytest.raises(GitError):
            paths_differ(repo, text, ["code.py"])


def test_a_directory_that_is_not_a_repository_cannot_say_whether_a_tree_differs(
    tmp_path: Path,
) -> None:
    with pytest.raises(GitError):
        paths_differ(tmp_path, "0" * 40, ["code.py"])


def test_a_missing_git_binary_is_an_error(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tree = git(repo, "rev-parse", "HEAD^{tree}")
    monkeypatch.setenv("PATH", str(repo / "nowhere"))
    with pytest.raises(GitError):
        paths_differ(repo, tree, ["code.py"])
