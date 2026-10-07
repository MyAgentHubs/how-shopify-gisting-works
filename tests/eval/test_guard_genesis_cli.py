import subprocess
from pathlib import Path

import pytest
from audit_support import BASE_FILES, Lab, baseline_text, fake_loader, new_lab
from guard_support import allow, git

from gisting.eval.cli import main
from gisting.eval.guard_signature import EMPTY_TREE, signed_message
from gisting.eval.ratchet_audit import audit


@pytest.fixture
def lab(tmp_path: Path) -> Lab:
    return new_lab(tmp_path)


def stage_genesis(lab: Lab) -> None:
    lab.stage({"eval/baseline.json": baseline_text(), **BASE_FILES})
    allow(lab.root, lab.key)
    git(lab.root, "add", "--", ".github/allowed_signers")


def test_guard_hash_genesis_prints_the_hash_of_every_protected_file_against_nothing(
    tmp_path: Path, lab: Lab, capsys: pytest.CaptureFixture[str]
) -> None:
    stage_genesis(lab)
    message = tmp_path / "genesis.msg"
    assert main(["guard-hash", "--genesis", "--root", str(lab.root), "--out", str(message)]) == 0
    lines = capsys.readouterr().out.splitlines()
    digest = lines[0].removeprefix("guard hash: ")
    assert lines[1] == f"parent tree: {EMPTY_TREE}"
    assert f"message written to: {message}" in lines
    assert lines[2:9] == [
        "protected paths changed:",
        "  .github/allowed_signers",
        "  data/eval/guard.json",
        "  eval/baseline.json",
        "  eval/genesis.json",
        "  eval/metrics.toml",
        "  scripts/check_eval_ratchet.py",
    ]
    assert lines[-1].endswith(f".github/eval-signatures/{digest}.sig")
    assert message.read_bytes() == signed_message(EMPTY_TREE, digest)


def test_the_printed_genesis_flow_produces_a_commit_the_audit_accepts(
    tmp_path: Path, lab: Lab, capsys: pytest.CaptureFixture[str]
) -> None:
    stage_genesis(lab)
    message = tmp_path / "genesis.msg"
    assert main(["guard-hash", "--genesis", "--root", str(lab.root), "--out", str(message)]) == 0
    printed = capsys.readouterr().out.splitlines()[-1]
    subprocess.run(
        ["ssh-keygen", "-q", "-Y", "sign", "-f", str(lab.key.private), "-n", "gisting-eval-guard"]
        + [str(message)],
        check=True,
        capture_output=True,
    )
    assert not (lab.root / ".github" / "eval-signatures").exists()
    subprocess.run(["sh", "-c", printed], cwd=lab.root, check=True, capture_output=True)
    git(lab.root, "commit", "-q", "-m", "genesis")
    result = audit(lab.root, fake_loader)
    assert result.anchor == lab.head()
    assert result.findings == ()


def test_guard_hash_genesis_refuses_a_staged_set_that_lacks_the_anchor_files(
    tmp_path: Path, lab: Lab, capsys: pytest.CaptureFixture[str]
) -> None:
    lab.stage({name: text for name, text in BASE_FILES.items() if name != "eval/metrics.toml"})
    message = tmp_path / "genesis.msg"
    assert main(["guard-hash", "--genesis", "--root", str(lab.root), "--out", str(message)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "eval/metrics.toml" in captured.err
    assert not message.exists()
