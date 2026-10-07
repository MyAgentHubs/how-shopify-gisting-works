import hashlib
import json
from pathlib import Path

from gisting.eval.report import RULES_VERSION_CHARS
from gisting.eval.report_tokens import as_object
from gisting.eval.tree import GitError, paths_differ
from gisting.shopify.jsonvalue import JsonObject, string_list

ROOT = Path(__file__).resolve().parents[3]
EPOCH_FILE = ROOT / "data" / "eval" / "replay-epoch-v1.json"
PREVIOUS_RULES_DIR = ROOT / "data" / "eval" / "previous_rules"
CROSS_EPOCH = "token replay skipped (cross-epoch)"


def epoch_paths(path: Path = EPOCH_FILE) -> tuple[str, ...]:
    paths = string_list(json.loads(path.read_text(encoding="utf-8")), "paths")
    if not paths or not all(paths):
        message = f"{path.name} needs a non-empty list of non-empty paths"
        raise ValueError(message)
    return paths


def previous_labels(directory: Path = PREVIOUS_RULES_DIR) -> frozenset[str]:
    return frozenset(
        hashlib.sha256(path.read_text(encoding="utf-8").removesuffix("\n").encode()).hexdigest()[
            :RULES_VERSION_CHARS
        ]
        for path in directory.glob("*.md")
    )


def crossed_epoch(root: Path, tree: str, stored: JsonObject) -> str | None:
    label = as_object(stored.get("run")).get("rules_version")
    shown = label[:RULES_VERSION_CHARS] if isinstance(label, str) else "none"
    try:
        if not paths_differ(root, tree, epoch_paths()):
            return None
        reason = f"replay inputs differ between tree {tree[:RULES_VERSION_CHARS]} and HEAD"
    except GitError:
        if label not in previous_labels():
            return None
        reason = f"tree {tree[:RULES_VERSION_CHARS]} is not in this clone and the rules are older"
    return f"{reason} (reported rules_version {shown})"
