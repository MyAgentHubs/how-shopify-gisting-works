import json
from collections import Counter
from dataclasses import dataclass

from gisting.eval.applicability import FILE_NAME as NOT_APPLICABLE_FILE
from gisting.eval.case_rules import CONTROL, POLICY_ACTIONS
from gisting.eval.ratchet_audit_tree import Tree
from gisting.shopify.jsonvalue import Json

CASES_DIR = "eval/cases"
CASE_FILE_DEPTH = 4
SHOWN = 3


@dataclass(frozen=True)
class CaseInfo:
    split: str
    policy_control: bool


def object_of(value: Json) -> dict[str, Json]:
    return value if isinstance(value, dict) else {}


def tree_cases(tree: Tree) -> dict[str, CaseInfo]:
    found: dict[str, CaseInfo] = {}
    for name in sorted(tree.blobs):
        parts = name.split("/")
        if not name.endswith(".jsonl") or len(parts) != CASE_FILE_DEPTH:
            continue
        if f"{parts[0]}/{parts[1]}" != CASES_DIR:
            continue
        for line in tree.blob_bytes(name).decode("utf-8").splitlines():
            case = object_of(json.loads(line))
            scenario = object_of(case.get("expect")).get("scenario")
            policy = case.get("red_line") == CONTROL and scenario in POLICY_ACTIONS
            found[str(case.get("id"))] = CaseInfo(parts[2], policy)
    return found


def row_ids(tree: Tree, directory: str) -> list[str]:
    text = (tree.read(f"{directory}/transcripts.jsonl") or b"").decode("utf-8")
    return [str(object_of(json.loads(line)).get("case_id")) for line in text.splitlines()]


def declared_splits(tree: Tree, directory: str) -> list[str] | None:
    report = object_of(json.loads(tree.read(f"{directory}/report.json") or b"null"))
    splits = object_of(report.get("cases")).get("splits")
    if isinstance(splits, list) and splits and all(isinstance(item, str) for item in splits):
        return [str(item) for item in splits]
    return None


def excused_ids(tree: Tree, directory: str) -> list[str]:
    raw = tree.read(f"{directory}/{NOT_APPLICABLE_FILE}")
    ids = object_of(json.loads(raw)).get("case_ids") if raw is not None else []
    return [str(item) for item in ids] if isinstance(ids, list) else [""]


def listing(label: str, ids: set[str]) -> list[str]:
    return [f"{len(ids)} {label} ({', '.join(sorted(ids)[:SHOWN])})"] if ids else []


def coverage_problems(tree: Tree, directory: str) -> list[str]:
    splits = declared_splits(tree, directory)
    if splits is None:
        return ["coverage: the report declares no splits"]
    universe = tree_cases(tree)
    ids, excused = row_ids(tree, directory), excused_ids(tree, directory)
    answered, left_out = set(ids), set(excused)
    expected = {case for case, info in universe.items() if info.split in splits} - left_out
    found = [
        *listing("cases have more than one row", {c for c, n in Counter(ids).items() if n > 1}),
        *listing("not applicable ids repeat", {c for c, n in Counter(excused).items() if n > 1}),
        *listing(
            "not applicable cases cannot be left out",
            {c for c in left_out if c not in universe or not universe[c].policy_control},
        ),
        *listing("cases left out as not applicable have rows", answered & left_out),
        *listing("cases of the declared splits have no row", expected - answered),
        *listing("rows are outside the declared splits", answered - expected),
    ]
    return [f"coverage: {item}" for item in found]
