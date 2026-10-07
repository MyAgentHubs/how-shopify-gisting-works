import json
from dataclasses import dataclass
from pathlib import Path

from gisting.eval.case_rules import case_problems
from gisting.eval.case_spec import EvalCase
from gisting.eval.dataclass_json import DecodeError, decode_as

CASES_DIR = "eval/cases"
PLAN_DIR = "data/demo-orders"
SPLITS = ("train", "dev", "sealed")
CASE_SUFFIX = ".jsonl"
SEALED_DIR = f"{CASES_DIR}/sealed"
SEALED_PLACEHOLDER = ".gitkeep"
SEALED_SUFFIXES = (".jsonl.age", ".enc")
PATH_DEPTH = 2


@dataclass(frozen=True)
class Problem:
    path: str
    line: int
    reason: str


@dataclass(frozen=True)
class LoadedCase:
    path: str
    line: int
    case: EvalCase


def case_files(root: Path) -> list[Path]:
    base = root / CASES_DIR
    return sorted(base.rglob(f"*{CASE_SUFFIX}")) if base.is_dir() else []


@dataclass(frozen=True)
class PlanOrder:
    order: str
    scenario: str
    carrier: str | None
    tracking: str | None


def plan_orders(root: Path, plan: str) -> list[PlanOrder] | None:
    path = root / PLAN_DIR / plan
    if not path.is_file():
        return None
    try:
        entries = json.loads(path.read_text(encoding="utf-8"))["entries"]
        return [
            PlanOrder(
                entry["order"],
                entry["scenario"],
                entry["tracking"]["company"] if entry["tracking"] else None,
                entry["tracking"]["number"] if entry["tracking"] else None,
            )
            for entry in entries
        ]
    except (OSError, ValueError, KeyError, TypeError):
        return None


def plan_canaries(root: Path, plan: str) -> dict[str, str] | None:
    path = root / PLAN_DIR / plan
    if not path.is_file():
        return None
    try:
        entries = json.loads(path.read_text(encoding="utf-8"))["entries"]
        return {entry["order"]: entry["canary"] for entry in entries}
    except (OSError, ValueError, KeyError, TypeError):
        return None


def layout_problems(relative: Path, case: EvalCase) -> list[str]:
    parts = relative.relative_to(CASES_DIR).parts
    if len(parts) != PATH_DEPTH or parts[0] not in SPLITS:
        return [f"case files live in {CASES_DIR}/<split>/<family>{CASE_SUFFIX}"]
    found: list[str] = []
    if case.split != parts[0]:
        found.append(f"split {case.split} does not match directory {parts[0]}")
    if f"{case.family}{CASE_SUFFIX}" != parts[1]:
        found.append(f"family {case.family} does not match file name {parts[1]}")
    return found


def line_problems(root: Path, relative: Path, text: str) -> tuple[EvalCase | None, list[str]]:
    if not text.strip():
        return None, ["blank line"]
    try:
        case = decode_as(EvalCase, json.loads(text))
    except (ValueError, DecodeError) as error:
        return None, [f"invalid case: {error}"]
    plan = case.fixtures.plan
    canaries = None if plan is None else plan_canaries(root, plan)
    orders = None if canaries is None else frozenset(canaries)
    found = layout_problems(relative, case)
    if plan is not None and canaries is None:
        found.append(f"plan {plan} is missing or unreadable")
    return case, [*found, *case_problems(case, orders)]


def load_file(root: Path, path: Path) -> tuple[list[LoadedCase], list[Problem]]:
    relative = path.relative_to(root)
    name = relative.as_posix()
    text = path.read_text(encoding="utf-8")
    loaded: list[LoadedCase] = []
    problems = [] if not text or text.endswith("\n") else [Problem(name, 1, "no final newline")]
    for number, line in enumerate(text.split("\n")[:-1] if text.endswith("\n") else [text], 1):
        case, reasons = line_problems(root, relative, line)
        problems += [Problem(name, number, reason) for reason in reasons]
        if case is not None:
            loaded.append(LoadedCase(name, number, case))
    return loaded, problems


def duplicate_ids(cases: list[LoadedCase]) -> list[Problem]:
    seen: dict[str, LoadedCase] = {}
    found: list[Problem] = []
    for item in cases:
        first = seen.setdefault(item.case.id, item)
        if first is not item:
            reason = f"id {item.case.id} already used at {first.path}:{first.line}"
            found.append(Problem(item.path, item.line, reason))
    return found


def load_cases(root: Path) -> tuple[list[LoadedCase], list[Problem]]:
    cases: list[LoadedCase] = []
    problems: list[Problem] = []
    for path in case_files(root):
        loaded, found = load_file(root, path)
        cases += loaded
        problems += found
    return cases, [*problems, *duplicate_ids(cases)]
