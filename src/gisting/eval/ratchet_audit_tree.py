from dataclasses import dataclass
from pathlib import Path

from gisting.eval.guard_git import Snapshot, git_bytes, tree_snapshot

SHORT = 12


@dataclass(frozen=True)
class Finding:
    commit: str
    message: str

    def describe(self) -> str:
        return f"{self.commit[:SHORT]}: {self.message}"


@dataclass(frozen=True)
class Tree:
    root: Path
    snapshot: Snapshot

    @property
    def blobs(self) -> dict[str, str]:
        return self.snapshot.blobs

    def blob_bytes(self, name: str) -> bytes:
        return git_bytes(self.root, "cat-file", "blob", self.blobs[name])

    def read(self, name: str) -> bytes | None:
        return self.blob_bytes(name) if name in self.blobs else None

    def names_in(self, directory: str) -> list[str]:
        return sorted(name for name in self.blobs if name.rpartition("/")[0] == directory)


def load_tree(root: Path, rev: str) -> Tree:
    return Tree(root, tree_snapshot(root, rev))
