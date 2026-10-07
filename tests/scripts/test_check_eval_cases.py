from pathlib import Path

import pytest
from conftest import SCRIPTS_DIR, Guard
from eval_repo import case_line, commit, git, init_repo, put, seed_plan

REPO = SCRIPTS_DIR.parent
SCRIPT = "check_eval_cases.py"
FAMILY_FILE = "eval/cases/dev/other_order_probe.jsonl"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    init_repo(tmp_path)
    return tmp_path


@pytest.fixture(autouse=True)
def without_environment_base(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GISTING_EVAL_CASES_BASE", raising=False)


def test_the_committed_skeleton_passes(guard: Guard) -> None:
    result = guard(SCRIPT, REPO)
    assert (result.returncode, result.stdout) == (0, "")


def test_an_untouched_history_passes(repo: Path, guard: Guard) -> None:
    git(repo, "checkout", "-q", "-b", "work")
    result = guard(SCRIPT, repo)
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")


def test_appending_a_case_and_adding_a_file_pass(repo: Path, guard: Guard) -> None:
    git(repo, "checkout", "-q", "-b", "work")
    put(repo, FAMILY_FILE, case_line(), case_line(id="second_case"), case_line(id="third_case"))
    put(
        repo,
        "eval/cases/train/fresh.jsonl",
        case_line(id="fresh_one", split="train", family="fresh"),
    )
    commit(repo)
    result = guard(SCRIPT, repo)
    assert (result.returncode, result.stderr) == (0, "")


def test_editing_an_existing_case_fails(repo: Path, guard: Guard) -> None:
    git(repo, "checkout", "-q", "-b", "work")
    put(repo, FAMILY_FILE, case_line(category="edited"), case_line(id="second_case"))
    commit(repo)
    result = guard(SCRIPT, repo)
    assert result.returncode == 1
    assert f"{FAMILY_FILE}:1: line 1 was changed or removed" in result.stderr


def test_removing_a_case_fails_even_uncommitted(repo: Path, guard: Guard) -> None:
    git(repo, "checkout", "-q", "-b", "work")
    put(repo, FAMILY_FILE, case_line())
    result = guard(SCRIPT, repo)
    assert result.returncode == 1
    assert f"{FAMILY_FILE}:2: line 2 was changed or removed" in result.stderr


def test_reordering_cases_fails(repo: Path, guard: Guard) -> None:
    git(repo, "checkout", "-q", "-b", "work")
    put(repo, FAMILY_FILE, case_line(id="second_case"), case_line())
    commit(repo)
    assert guard(SCRIPT, repo).returncode == 1


def test_deleting_a_case_file_fails(repo: Path, guard: Guard) -> None:
    git(repo, "checkout", "-q", "-b", "work")
    (repo / FAMILY_FILE).unlink()
    result = guard(SCRIPT, repo)
    assert result.returncode == 1
    assert f"{FAMILY_FILE}:1: file was deleted" in result.stderr


def test_a_modification_already_committed_on_main_is_caught_against_the_parent(
    repo: Path, guard: Guard
) -> None:
    put(repo, FAMILY_FILE, case_line(category="edited"), case_line(id="second_case"))
    commit(repo)
    result = guard(SCRIPT, repo)
    assert result.returncode == 1
    assert "line 1 was changed or removed" in result.stderr


def test_appending_on_main_passes_against_the_parent(repo: Path, guard: Guard) -> None:
    put(repo, FAMILY_FILE, case_line(), case_line(id="second_case"), case_line(id="third_case"))
    commit(repo)
    assert guard(SCRIPT, repo).returncode == 0


def test_an_explicit_base_catches_a_change_hidden_in_an_older_commit(
    repo: Path, guard: Guard
) -> None:
    first = git(repo, "rev-parse", "HEAD")
    put(repo, FAMILY_FILE, case_line(category="edited"), case_line(id="second_case"))
    commit(repo)
    put(
        repo,
        FAMILY_FILE,
        case_line(category="edited"),
        case_line(id="second_case"),
        case_line(id="x"),
    )
    commit(repo)
    assert guard(SCRIPT, repo).returncode == 0
    result = guard(SCRIPT, repo, "--base", first)
    assert result.returncode == 1
    assert "line 1 was changed or removed" in result.stderr


def test_an_unresolvable_base_falls_back_loudly(repo: Path, guard: Guard) -> None:
    git(repo, "checkout", "-q", "-b", "work")
    put(repo, FAMILY_FILE, case_line(category="edited"), case_line(id="second_case"))
    result = guard(SCRIPT, repo, "--base", "0" * 40)
    assert result.returncode == 1
    assert "base 0000000000000000000000000000000000000000 not found" in result.stderr


def test_without_git_the_append_check_is_skipped_loudly(tmp_path: Path, guard: Guard) -> None:
    seed_plan(tmp_path)
    put(tmp_path, FAMILY_FILE, case_line())
    result = guard(SCRIPT, tmp_path)
    assert result.returncode == 0
    assert "append-only check skipped" in result.stderr


def test_schema_and_layout_problems_fail_without_git(tmp_path: Path, guard: Guard) -> None:
    seed_plan(tmp_path)
    put(tmp_path, "eval/cases/train/other_order_probe.jsonl", case_line())
    result = guard(SCRIPT, tmp_path)
    assert result.returncode == 1
    assert "does not match directory train" in result.stderr


@pytest.mark.parametrize("name", ["leaked.jsonl", "LEAKED.JSONL", "notes.txt", "leaked.jsonl.bak"])
def test_a_plaintext_file_in_the_sealed_directory_fails(
    tmp_path: Path, guard: Guard, name: str
) -> None:
    seed_plan(tmp_path)
    put(tmp_path, f"eval/cases/sealed/{name}", case_line(split="sealed"))
    result = guard(SCRIPT, tmp_path)
    assert result.returncode == 1
    assert f"eval/cases/sealed/{name}:1: sealed cases must be encrypted" in result.stderr


@pytest.mark.parametrize("name", [".gitkeep", "family.jsonl.age", "family.enc"])
def test_a_placeholder_or_encrypted_file_in_the_sealed_directory_passes(
    tmp_path: Path, guard: Guard, name: str
) -> None:
    seed_plan(tmp_path)
    put(tmp_path, f"eval/cases/sealed/{name}", "opaque")
    result = guard(SCRIPT, tmp_path)
    assert result.returncode == 0
    assert "sealed" not in result.stderr
