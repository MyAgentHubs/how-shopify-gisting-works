import subprocess
import tempfile
from pathlib import Path

import pytest
from guard_support import allow, git, make_key, new_repo, sha, write

from gisting.eval.cli import main
from gisting.eval.guard_signature import Valid, signed_message, verify

MODE = "100644"

SIGN_PREFIX = "ssh-keygen -Y sign -f ~/.ssh/gisting_signing -n gisting-eval-guard "


@pytest.fixture
def scratch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path / "scratch"
    directory.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", None)
    monkeypatch.setenv("TMPDIR", str(directory))
    return directory


def staged_baseline_change(tmp_path: Path) -> tuple[Path, str, str]:
    root = new_repo(tmp_path / "repo", {"eval/baseline.json": "old", "README.md": "a"})
    write(root, {"eval/baseline.json": "new", "README.md": "b"})
    git(root, "add", "--", "eval/baseline.json", "README.md")
    fields = ["eval/baseline.json", MODE, sha("old"), MODE, sha("new")]
    return root, sha("\0".join(fields) + "\n"), git(root, "rev-parse", "HEAD^{tree}")


def test_guard_hash_prints_the_hash_the_paths_and_the_next_commands(
    tmp_path: Path, scratch: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root, digest, tree = staged_baseline_change(tmp_path)
    assert main(["guard-hash", "--root", str(root)]) == 0
    captured = capsys.readouterr()
    message = scratch / f"gisting-guard-{digest[:12]}.msg"
    lines = captured.out.splitlines()
    assert captured.err == ""
    assert lines[:4] == [
        f"guard hash: {digest}",
        f"parent tree: {tree}",
        "protected paths changed:",
        "  eval/baseline.json",
    ]
    assert lines[4].startswith("baseline classification unavailable")
    assert lines[5] == "signature required: yes"
    assert lines[6:] == [
        f"message written to: {message}",
        "run these two commands from the repository root:",
        f"{SIGN_PREFIX}{message}",
        f"mkdir -p .github/eval-signatures && "
        f"mv {message}.sig .github/eval-signatures/{digest}.sig && "
        f"git add .github/eval-signatures/{digest}.sig",
    ]
    assert message.read_bytes() == signed_message(tree, digest)


def test_guard_hash_writes_the_message_where_asked(tmp_path: Path, scratch: Path) -> None:
    root, digest, tree = staged_baseline_change(tmp_path)
    target = tmp_path / "custom.msg"
    assert main(["guard-hash", "--root", str(root), "--out", str(target)]) == 0
    assert target.read_bytes() == signed_message(tree, digest)
    assert not (scratch / "gisting-guard.msg").exists()


def test_guard_hash_says_no_signature_is_needed_for_unrelated_changes(
    tmp_path: Path, scratch: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = new_repo(tmp_path / "repo", {"README.md": "a"})
    write(root, {"README.md": "b", "notes.txt": "n"})
    git(root, "add", "--", "README.md", "notes.txt")
    assert main(["guard-hash", "--root", str(root)]) == 0
    captured = capsys.readouterr()
    assert captured.out == "no protected paths changed; no signature needed\n"
    assert captured.err == ""
    assert list(scratch.iterdir()) == []


def test_guard_hash_fails_loudly_without_a_guard_file(
    tmp_path: Path, scratch: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    write(root, {"README.md": "a"})
    git(root, "add", "--", "README.md")
    git(root, "commit", "-q", "-m", "init")
    assert main(["guard-hash", "--root", str(root)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "guard.json" in captured.err
    assert list(scratch.iterdir()) == []


def test_guard_hash_fails_when_the_message_cannot_be_written(
    tmp_path: Path, scratch: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root, _, _ = staged_baseline_change(tmp_path)
    assert main(["guard-hash", "--root", str(root), "--out", str(tmp_path / "no" / "dir")]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "guard-hash" in captured.err


def test_the_printed_message_signs_into_a_signature_that_verifies(
    tmp_path: Path, scratch: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root, digest, tree = staged_baseline_change(tmp_path)
    key = make_key(tmp_path)
    allow(root, key)
    assert main(["guard-hash", "--root", str(root)]) == 0
    message = next(scratch.glob("gisting-guard-*.msg"))
    printed = capsys.readouterr().out.splitlines()[-1]
    subprocess.run(
        ["ssh-keygen", "-q", "-Y", "sign", "-f", str(key.private), "-n", "gisting-eval-guard"]
        + [str(message)],
        check=True,
        capture_output=True,
    )
    assert not (root / ".github" / "eval-signatures").exists()
    subprocess.run(["sh", "-c", printed], cwd=root, check=True, capture_output=True)
    assert isinstance(verify(root, digest, tree), Valid)
    assert git(root, "diff", "--cached", "--name-only").count(f"{digest}.sig") == 1
