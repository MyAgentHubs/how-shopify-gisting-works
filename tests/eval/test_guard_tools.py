import os
import stat
from collections.abc import Callable
from pathlib import Path

import pytest
from audit_support import BASELINE, Lab, baseline_text, culprits, epoch, messages, new_lab, run
from guard_support import allow, git, make_key

import gisting.eval.guard_signature as guard_signature
from gisting.eval.guard_git import git_bytes, staged_change, tree_snapshot
from gisting.eval.guard_signature import GuardError, Invalid, Valid, system_tool, verify

DIGEST = "d" * 64
TREE = "a" * 40
Decoy = Callable[[], Path]


def fake_tool(directory: Path, name: str, body: str) -> None:
    directory.mkdir(exist_ok=True)
    path = directory / name
    path.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


@pytest.fixture
def decoy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Decoy:
    marker = tmp_path / "decoy-ran"

    def install() -> Path:
        directory = tmp_path / "decoy"
        fake_tool(directory, "ssh-keygen", f"touch {marker}\nexit 0")
        fake_tool(directory, "git", f"touch {marker}\nexit 0")
        monkeypatch.setenv("PATH", f"{directory}{os.pathsep}{os.environ['PATH']}")
        return marker

    return install


@pytest.fixture
def lab(tmp_path: Path) -> Lab:
    return new_lab(tmp_path)


def test_a_decoy_ssh_keygen_that_always_succeeds_cannot_verify_a_garbage_signature(
    tmp_path: Path, decoy: Decoy
) -> None:
    key = make_key(tmp_path)
    allow(tmp_path, key)
    signature = tmp_path / ".github" / "eval-signatures" / f"{DIGEST}.sig"
    signature.parent.mkdir(parents=True)
    signature.write_text("garbage", encoding="utf-8")
    marker = decoy()
    result = verify(tmp_path, DIGEST, TREE)
    assert isinstance(result, Invalid)
    assert not isinstance(result, Valid)
    assert not marker.exists()


def test_a_decoy_git_on_the_path_is_never_run(lab: Lab, decoy: Decoy) -> None:
    lab.genesis()
    marker = decoy()
    assert git_bytes(lab.root, "rev-parse", "HEAD").decode().strip() == lab.head()
    assert tree_snapshot(lab.root, "HEAD").blobs
    assert not marker.exists()


def test_the_decoy_cannot_turn_an_unsigned_loosening_into_a_pass(lab: Lab, decoy: Decoy) -> None:
    lab.genesis()
    bad = lab.commit({BASELINE: baseline_text(epoch(rate=0.3))})
    marker = decoy()
    result = run(lab)
    assert culprits(result) == {bad}
    assert "not signed" in messages(result)
    assert not marker.exists()


def test_the_audit_ignores_git_variables_that_redirect_the_repository(
    lab: Lab, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    lab.genesis()
    lab.commit({"notes.txt": "x"})
    other = tmp_path / "elsewhere"
    other.mkdir()
    redirects = {
        "GIT_DIR": str(other),
        "GIT_INDEX_FILE": str(other / "index"),
        "GIT_OBJECT_DIRECTORY": str(other / "objects"),
        "GIT_NAMESPACE": "nowhere",
    }
    for name, value in redirects.items():
        monkeypatch.setenv(name, value)
    assert run(lab).findings == ()


def test_a_missing_system_tool_fails_closed_without_a_path_search(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_tool(tmp_path / "bin", "git", "exit 0")
    monkeypatch.setattr(guard_signature, "SYSTEM_BIN", tmp_path / "empty")
    monkeypatch.setenv("PATH", str(tmp_path / "bin"))
    with pytest.raises(GuardError, match="not looked up on PATH"):
        system_tool("git")
    with pytest.raises(GuardError, match="not looked up on PATH"):
        git_bytes(tmp_path, "status")


def test_the_staged_change_still_works_without_a_home_directory(
    lab: Lab, monkeypatch: pytest.MonkeyPatch
) -> None:
    lab.genesis()
    git(lab.root, "update-index", "--chmod=+x", "scripts/check_eval_ratchet.py")
    monkeypatch.delenv("HOME", raising=False)
    assert staged_change(lab.root).paths == ("scripts/check_eval_ratchet.py",)
