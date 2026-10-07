import re
from dataclasses import dataclass
from pathlib import Path

from gisting.eval.guard_git import GENESIS_FILE, git_bytes
from gisting.eval.guard_signature import GuardError
from gisting.eval.ratchet_audit_tree import SHORT, Finding

NOT_LINEAR = "the commit has {count} parents; the history after the anchor must be linear"
BASE_SHA = re.compile(r"[0-9a-f]{4,64}")
OFF_CHAIN = (
    f"{GENESIS_FILE} is introduced off the first-parent chain of HEAD: "
    "a merge swallowed the anchored history or the anchor was dropped"
)


@dataclass(frozen=True)
class History:
    chain: tuple[str, ...]
    parents: dict[str, tuple[str, ...]]
    introducers: tuple[str, ...]

    @property
    def head(self) -> str:
        return self.chain[-1]

    @property
    def anchor(self) -> str | None:
        chain = set(self.chain)
        return next((commit for commit in self.introducers if commit in chain), None)


def rev_list(root: Path, *options: str) -> list[str]:
    return git_bytes(root, "rev-list", *options, "HEAD").decode().splitlines()


def has_genesis(root: Path, commits: list[str]) -> dict[str, bool]:
    queries = "".join(f"{commit}:{GENESIS_FILE}\n" for commit in commits).encode()
    answers = git_bytes(root, "cat-file", "--batch-check", stdin=queries).decode().splitlines()
    return {
        commit: answer.split(" ")[1] == "blob"
        for commit, answer in zip(commits, answers, strict=True)
    }


def load_history(root: Path) -> History:
    rows = [line.split() for line in rev_list(root, "--topo-order", "--parents")]
    parents = {row[0]: tuple(row[1:]) for row in rows}
    oldest_first = [row[0] for row in reversed(rows)]
    present = has_genesis(root, oldest_first)
    introducers = tuple(
        commit
        for commit in oldest_first
        if present[commit] and not any(present[parent] for parent in parents[commit])
    )
    return History(tuple(rev_list(root, "--first-parent", "--reverse")), parents, introducers)


def genesis_findings(history: History) -> list[Finding]:
    if not history.introducers:
        return []
    first, *later = history.introducers
    again = f"{GENESIS_FILE} is introduced here and by {first[:SHORT]}; only once is allowed"
    found = [Finding(commit, again) for commit in later]
    return found if history.anchor else [Finding(first, OFF_CHAIN), *found]


def linear_findings(history: History) -> list[Finding]:
    anchor = history.anchor
    if anchor is None:
        return []
    after = history.chain[history.chain.index(anchor) + 1 :]
    return [
        Finding(commit, NOT_LINEAR.format(count=len(history.parents[commit])))
        for commit in after
        if len(history.parents[commit]) != 1
    ]


def existing_commit(root: Path, base: str) -> str | None:
    try:
        found = git_bytes(root, "rev-parse", "--verify", "--quiet", f"{base}^{{commit}}")
    except GuardError:
        return None
    return found.decode().strip()


def base_findings(root: Path, history: History, base: str | None) -> list[Finding]:
    if base is None:
        return []
    if not BASE_SHA.fullmatch(base):
        message = f"--base needs a commit sha (4 to 64 lowercase hex digits), not {base!r}"
        raise GuardError(message)
    tip = existing_commit(root, base)
    if tip is None:
        return [
            Finding(history.head, f"the previous tip {base} is not a commit of this repository")
        ]
    if tip in history.chain:
        return []
    message = (
        f"the previous tip {tip[:SHORT]} is not on the first-parent chain of HEAD: "
        "the audited history was rewritten or bypassed"
    )
    return [Finding(history.head, message)]


def history_findings(root: Path, history: History, base: str | None) -> list[Finding]:
    return [
        *genesis_findings(history),
        *linear_findings(history),
        *base_findings(root, history, base),
    ]
