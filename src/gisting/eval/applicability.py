import json
from collections.abc import Collection, Mapping, Sequence
from pathlib import Path

from gisting.eval.case_files import LoadedCase
from gisting.eval.case_rules import CONTROL, POLICY_ACTIONS
from gisting.eval.case_spec import EvalCase
from gisting.prompt.schema import load_tool_schemas
from gisting.shopify.jsonvalue import Json, JsonObject

POLICY_TOOL = "search_policy"
REASON = "search_policy not in production tools"
FILE_NAME = "not_applicable.json"
TOOLS_PATH = ("prompts", "tools")


class NotApplicableError(ValueError):
    pass


def production_tools(root: Path) -> frozenset[str]:
    return frozenset(load_tool_schemas(root.joinpath(*TOOLS_PATH)))


def needs_policy_tool(case: EvalCase) -> bool:
    return case.red_line == CONTROL and case.expect.scenario in POLICY_ACTIONS


def partition_applicable(
    loaded: Sequence[LoadedCase], tools: Collection[str]
) -> tuple[list[LoadedCase], list[LoadedCase]]:
    kept: list[LoadedCase] = []
    skipped: list[LoadedCase] = []
    for item in loaded:
        gone = POLICY_TOOL not in tools and needs_policy_tool(item.case)
        (skipped if gone else kept).append(item)
    return kept, skipped


def record_of(ids: Sequence[str]) -> JsonObject:
    return {"reason": REASON if ids else None, "case_ids": [*sorted(ids)]}


def write_record(directory: Path, ids: Sequence[str]) -> None:
    text = json.dumps(record_of(ids), indent=2, sort_keys=True) + "\n"
    (directory / FILE_NAME).write_text(text, encoding="utf-8")


def read_record(directory: Path) -> JsonObject | None:
    path = directory / FILE_NAME
    if not path.is_file():
        return None
    document: Json = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        message = f"{FILE_NAME} is not an object"
        raise NotApplicableError(message)
    return document


def record_problems(
    record: JsonObject, cases: Mapping[str, EvalCase], answered: Collection[str]
) -> list[str]:
    ids = record.get("case_ids")
    if not isinstance(ids, list) or not all(isinstance(item, str) for item in ids):
        return ["case_ids is not a list of ids"]
    found: list[str] = []
    expected = REASON if ids else None
    if record.get("reason") != expected:
        found.append(f"the reason must be {expected!r}")
    if ids != sorted(set(map(str, ids))):
        found.append("case_ids must be sorted and unique")
    for item in map(str, ids):
        case = cases.get(item)
        if case is None or not needs_policy_tool(case):
            found.append(f"{item} is not a control case that needs {POLICY_TOOL}")
        if item in answered:
            found.append(f"{item} is marked not applicable but has a transcript")
    return found


def section_of(record: JsonObject) -> JsonObject:
    ids = record["case_ids"]
    return {
        "count": len(ids) if isinstance(ids, list) else 0,
        "reason": record["reason"],
        "case_ids": ids,
    }
