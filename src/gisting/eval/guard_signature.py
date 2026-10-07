import hashlib
import json
import os
import re
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

from gisting.shopify.jsonvalue import Json

NAMESPACE = "gisting-eval-guard"
IDENTITY = "gisting-signer"
MESSAGE_TAG = "gisting-eval-guard-v2"
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
ALLOWED_SIGNERS = ".github/allowed_signers"
SIGNATURE_DIR = ".github/eval-signatures"
ABSENT = "absent"
HEX_DIGEST = re.compile(r"[0-9a-f]{64}")
TREE_ID = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
GLOB_TOKENS = {"**/": "(?:.*/)?", "**": ".*", "*": "[^/]*", "?": "[^/]"}
GLOB_SPLIT = re.compile(r"(\*\*/|\*\*|\*|\?)")


class File(NamedTuple):
    mode: str
    content: bytes


Side = Mapping[str, File | None]

SYSTEM_BIN = Path("/usr/bin")
TOOL_ENV = {"PATH": "/usr/bin:/bin", "LC_ALL": "C"}


class GuardError(ValueError):
    pass


def system_tool(name: str) -> str:
    path = SYSTEM_BIN / name
    if not (path.is_file() and os.access(path, os.X_OK)):
        message = f"{path} is missing or not executable; {name} is not looked up on PATH"
        raise GuardError(message)
    return str(path)


@dataclass(frozen=True)
class Valid:
    pass


@dataclass(frozen=True)
class Missing:
    path: Path


@dataclass(frozen=True)
class Invalid:
    stderr: str


Signature = Valid | Missing | Invalid


def parse_patterns(blob: bytes) -> tuple[str, ...]:
    try:
        document: Json = json.loads(blob)
    except ValueError as error:
        message = "guard.json is not valid JSON"
        raise GuardError(message) from error
    paths = document.get("paths") if isinstance(document, dict) else None
    if not isinstance(paths, list) or not paths:
        message = "guard.json needs a non-empty list of paths"
        raise GuardError(message)
    patterns = tuple(path for path in paths if isinstance(path, str) and path)
    if len(patterns) != len(paths):
        message = "guard.json paths must all be non-empty strings"
        raise GuardError(message)
    return patterns


def glob_regex(pattern: str) -> re.Pattern[str]:
    return re.compile(
        "".join(GLOB_TOKENS.get(part, re.escape(part)) for part in GLOB_SPLIT.split(pattern))
    )


def protected_names(patterns: Sequence[str], names: Sequence[str]) -> list[str]:
    regexes = [glob_regex(pattern) for pattern in patterns]
    return sorted({name for name in names if any(regex.fullmatch(name) for regex in regexes)})


def is_utf8(name: str) -> bool:
    try:
        name.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def path_problems(patterns: Sequence[str], names: Sequence[str]) -> list[str]:
    exact = [glob_regex(pattern) for pattern in patterns]
    folded = [re.compile(regex.pattern, re.IGNORECASE) for regex in exact]
    problems: list[str] = []
    for name in sorted(set(names)):
        if not is_utf8(name):
            problems.append(f"{name!r} is not valid UTF-8")
        elif any(f.fullmatch(name) for f in folded) and not any(e.fullmatch(name) for e in exact):
            problems.append(f"{name!r} differs only by letter case from a protected path")
    return problems


def changed_paths(patterns: Sequence[str], parent: Side, new: Side) -> list[str]:
    names = protected_names(patterns, [*parent, *new])
    return [name for name in names if parent.get(name) != new.get(name)]


def side_fields(file: File | None) -> str:
    if file is None:
        return f"{ABSENT}\0{ABSENT}"
    return f"{file.mode}\0{hashlib.sha256(file.content).hexdigest()}"


def diff_hash(patterns: Sequence[str], parent: Side, new: Side) -> str:
    records = "".join(
        f"{path}\0{side_fields(parent.get(path))}\0{side_fields(new.get(path))}\n"
        for path in changed_paths(patterns, parent, new)
    )
    return hashlib.sha256(records.encode()).hexdigest()


def signed_message(parent_tree: str, digest: str) -> bytes:
    return f"{MESSAGE_TAG}\n{parent_tree}\n{digest}\n".encode()


def signature_file(root: Path, digest: str) -> Path:
    return root / SIGNATURE_DIR / f"{digest}.sig"


def verify(root: Path, digest: str, parent_tree: str) -> Signature:
    if not HEX_DIGEST.fullmatch(digest):
        return Invalid("malformed digest: expected 64 lowercase hex characters")
    if not TREE_ID.fullmatch(parent_tree):
        return Invalid("malformed parent tree: expected 40 or 64 lowercase hex characters")
    signature = signature_file(root, digest)
    if not signature.is_file():
        return Missing(signature)
    command = [
        system_tool("ssh-keygen"),
        "-Y",
        "verify",
        "-f",
        str(root / ALLOWED_SIGNERS),
        "-I",
        IDENTITY,
        "-n",
        NAMESPACE,
        "-s",
        str(signature),
    ]
    try:
        done = subprocess.run(
            command,
            input=signed_message(parent_tree, digest),
            capture_output=True,
            check=False,
            env=TOOL_ENV,
        )
    except OSError as error:
        message = f"cannot run ssh-keygen: {error}"
        raise GuardError(message) from error
    if done.returncode == 0:
        return Valid()
    return Invalid(done.stderr.decode(errors="replace").strip())
