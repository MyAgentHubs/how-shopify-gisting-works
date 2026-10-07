#!/usr/bin/env python3
import fnmatch
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_ENDPOINT = "https://huggingface.co"
TIMEOUT_SECONDS = 60
CHUNK_BYTES = 1 << 20
EXPECTED_FILE = "HUB_LFS_SHA256"
MIN_ARGS = 5
DEFAULT_ATTEMPTS = 5
DEFAULT_BACKOFF_SECONDS = 2.0
EXIT_MISMATCH = 1
EXIT_NETWORK = 2
HTTP_TOO_MANY_REQUESTS = 429
HTTP_SERVER_ERROR = 500


class HubUnavailableError(Exception):
    def __init__(self, repo: str, revision: str, cause: object = "no attempts made") -> None:
        super().__init__(f"cannot read hub metadata for {repo}@{revision}: {cause}")


def is_transient(error: Exception) -> bool:
    if isinstance(error, urllib.error.HTTPError):
        return error.code == HTTP_TOO_MANY_REQUESTS or error.code >= HTTP_SERVER_ERROR
    return isinstance(error, OSError | ValueError)


def fetch_siblings(repo: str, revision: str) -> list[dict[str, Any]]:
    endpoint = os.environ.get("GISTING_HUB_ENDPOINT", DEFAULT_ENDPOINT).rstrip("/")
    request = urllib.request.Request(f"{endpoint}/api/models/{repo}/revision/{revision}?blobs=true")
    token = os.environ.get("HF_TOKEN")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    attempts = max(1, int(os.environ.get("GISTING_HUB_RETRIES", DEFAULT_ATTEMPTS)))
    backoff = float(os.environ.get("GISTING_HUB_BACKOFF", DEFAULT_BACKOFF_SECONDS))
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                return json.load(response)["siblings"]
        except (OSError, ValueError, KeyError) as error:
            if attempt + 1 == attempts or not is_transient(error):
                raise HubUnavailableError(repo, revision, error) from error
            time.sleep(backoff * 2**attempt)
    raise HubUnavailableError(repo, revision)


def lfs_expectations(siblings: list[dict[str, Any]], patterns: list[str]) -> dict[str, str]:
    expected: dict[str, str] = {}
    for sibling in siblings:
        lfs: dict[str, Any] = sibling.get("lfs") or {}
        sha = lfs.get("sha256")
        name = sibling["rfilename"]
        if sha and any(fnmatch.fnmatchcase(name, pattern) for pattern in patterns):
            expected[name] = sha
    return expected


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def compare(expected: dict[str, str], directory: Path) -> dict[str, Any]:
    missing: list[str] = []
    mismatched: list[str] = []
    verified: list[str] = []
    for name, sha in sorted(expected.items()):
        path = directory / name
        if not path.is_file():
            missing.append(name)
        elif sha256_file(path) != sha:
            mismatched.append(name)
        else:
            verified.append(name)
    return {
        "ok": not (missing or mismatched),
        "reason": "hash_mismatch" if missing or mismatched else "ok",
        "verified": verified,
        "missing": missing,
        "mismatched": mismatched,
    }


def write_expected(expected: dict[str, str], directory: Path) -> None:
    lines = [f"{sha}  {name}\n" for name, sha in sorted(expected.items())]
    (directory / EXPECTED_FILE).write_text("".join(lines))


def main(argv: list[str]) -> int:
    if len(argv) < MIN_ARGS:
        sys.exit("usage: hub_lfs_check.py <repo> <revision> <dir> <pattern> [pattern ...]")
    repo, revision, directory, patterns = argv[1], argv[2], Path(argv[3]), argv[4:]
    try:
        siblings = fetch_siblings(repo, revision)
    except HubUnavailableError as error:
        sys.stderr.write(f"error: {error}\n")
        sys.stdout.write(
            json.dumps({"ok": False, "reason": "hub_unreachable", "error": str(error)}) + "\n"
        )
        return EXIT_NETWORK
    expected = lfs_expectations(siblings, patterns)
    result = compare(expected, directory)
    if result["ok"]:
        write_expected(expected, directory)
    sys.stdout.write(json.dumps(result) + "\n")
    return 0 if result["ok"] else EXIT_MISMATCH


if __name__ == "__main__":
    sys.exit(main(sys.argv))
