import hashlib
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

NAMESPACE = "gisting-eval-guard"
IDENTITY = "gisting-signer"
GUARD_FILE = "data/eval/guard.json"
PATTERNS = ["eval/baseline.json", "src/gisting/eval/baseline*.py", GUARD_FILE]
GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.com",
    "HOME": "/nonexistent",
    "PATH": os.environ["PATH"],
}


def git(root: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, env=GIT_ENV, check=True
    )
    return done.stdout.strip()


def write(root: Path, files: dict[str, str]) -> None:
    for name, text in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")


def guard_text(patterns: list[str] = PATTERNS) -> str:
    return json.dumps({"paths": patterns})


def new_repo(root: Path, files: dict[str, str]) -> Path:
    root.mkdir(parents=True)
    git(root, "init", "-q", "-b", "main")
    write(root, {GUARD_FILE: guard_text(), **files})
    git(root, "add", "--", *files, GUARD_FILE)
    git(root, "commit", "-q", "-m", "init")
    return root


def commit_all(root: Path, files: dict[str, str]) -> None:
    write(root, files)
    git(root, "add", "--", *files)
    git(root, "commit", "-q", "-m", "next")


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


@dataclass(frozen=True)
class SigningKey:
    private: Path
    public_line: str


def make_key(directory: Path, name: str = "key") -> SigningKey:
    private = directory / name
    subprocess.run(
        ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "test", "-f", str(private)],
        check=True,
        capture_output=True,
    )
    fields = private.with_suffix(".pub").read_text(encoding="utf-8").split()
    return SigningKey(private, f"{fields[0]} {fields[1]}")


def allow(
    root: Path, key: SigningKey, identity: str = IDENTITY, namespace: str = NAMESPACE
) -> None:
    target = root / ".github" / "allowed_signers"
    target.parent.mkdir(parents=True, exist_ok=True)
    line = f'{identity} namespaces="{namespace}" {key.public_line}\n'
    target.write_text(line, encoding="utf-8")


def sign(
    root: Path, key: SigningKey, digest: str, message: bytes, namespace: str = NAMESPACE
) -> Path:
    scratch = root / f"message-{digest[:8]}"
    scratch.write_bytes(message)
    subprocess.run(
        ["ssh-keygen", "-q", "-Y", "sign", "-f", str(key.private), "-n", namespace, str(scratch)],
        check=True,
        capture_output=True,
    )
    target = root / ".github" / "eval-signatures" / f"{digest}.sig"
    target.parent.mkdir(parents=True, exist_ok=True)
    scratch.with_name(scratch.name + ".sig").replace(target)
    return target
