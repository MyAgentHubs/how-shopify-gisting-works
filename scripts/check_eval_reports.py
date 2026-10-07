#!/usr/bin/env python3
import json
import os
import re
import sys
from collections.abc import Sequence
from pathlib import Path

import guardlib
from guardlib import Violation

from gisting.eval.applicability import read_record
from gisting.eval.case_files import load_cases
from gisting.eval.case_spec import EvalCase
from gisting.eval.cli_grade import REPORT_FILE
from gisting.eval.redact import DEMO_EMAIL
from gisting.eval.replay import replay_problems
from gisting.eval.replay_epoch import CROSS_EPOCH, crossed_epoch
from gisting.eval.report import ReportError, build_report, load_rows, with_not_applicable
from gisting.eval.report_identity import identity_problems
from gisting.eval.runner import MODES, TRANSCRIPTS_FILE
from gisting.model_server.config import load_config
from gisting.prompt.tokenizer import PromptTokenizer, TokenizerUnavailable
from gisting.shopify.jsonvalue import Json, JsonObject

REPORTS = "eval/reports"
TREE_SHA = re.compile(r"[0-9a-f]{40}")
SECRET_PATTERNS = (
    re.compile(DEMO_EMAIL, re.IGNORECASE),
    re.compile(r"hf_[A-Za-z0-9]{20,}"),
    re.compile(r"shp(?:at|ss|ca|pa)_[A-Za-z0-9]{16,}"),
    re.compile(r"GISTING_EMAIL_SECRET\s*="),
)
VOLATILE = ("rules_version",)
SHOWN = 5


def differences(stored: Json, fresh: Json, path: str = "") -> list[str]:
    if isinstance(stored, dict) and isinstance(fresh, dict):
        return [
            item
            for key in sorted(set(stored) | set(fresh))
            for item in differences(stored.get(key), fresh.get(key), f"{path}.{key}".lstrip("."))
        ]
    return [] if stored == fresh else [path or "(root)"]


def without_volatile(report: JsonObject) -> JsonObject:
    run = report.get("run")
    if not isinstance(run, dict):
        return report
    return {**report, "run": {key: value for key, value in run.items() if key not in VOLATILE}}


def secret_violations(relative: str, text: str) -> list[Violation]:
    return [
        Violation(relative, 1, "contains a value that looks like a secret or a demo email")
        for pattern in SECRET_PATTERNS
        if pattern.search(text)
    ]


def layout_violations(relative: str, directory: Path) -> list[Violation]:
    found: list[Violation] = []
    if not TREE_SHA.fullmatch(directory.parent.name):
        found.append(Violation(relative, 1, "report directories are named by a 40-hex tree sha"))
    if directory.name not in MODES:
        found.append(Violation(relative, 1, f"mode directory must be one of {', '.join(MODES)}"))
    for name in (REPORT_FILE, TRANSCRIPTS_FILE):
        if not (directory / name).is_file():
            found.append(Violation(relative, 1, f"{name} is missing"))
    return found


def identity_violations(
    relative: str, directory: Path, stored: JsonObject, rows: Sequence[JsonObject]
) -> list[Violation]:
    problems = identity_problems(directory, stored, rows)
    found = [Violation(relative, 1, item.describe()) for item in problems[:SHOWN]]
    cases = stored.get("cases")
    if not isinstance(cases, dict) or cases.get("complete") is not True:
        found.append(Violation(relative, 1, "an incomplete report (run errors) must not be kept"))
    return found


def readable_rows(directory: Path) -> list[JsonObject]:
    try:
        return load_rows(directory / TRANSCRIPTS_FILE)
    except (ReportError, ValueError):
        return []


def regrade_violations(
    relative: str, directory: Path, stored: JsonObject, cases: dict[str, EvalCase], root: Path
) -> tuple[list[Violation], list[JsonObject]]:
    text = (directory / TRANSCRIPTS_FILE).read_text(encoding="utf-8")
    try:
        rows = load_rows(directory / TRANSCRIPTS_FILE)
        built = build_report(rows, cases, root, directory.parent.name, text)
        fresh = with_not_applicable(built, read_record(directory), rows, cases)
    except (ReportError, ValueError) as error:
        return [Violation(relative, 1, f"cannot regrade the transcripts: {error}")], []
    changed = differences(without_volatile(stored), without_volatile(fresh))
    if not changed:
        return [], rows
    reason = f"regrading the transcripts differs from report.json at {', '.join(changed[:SHOWN])}"
    return [Violation(relative, 1, reason)], rows


def replay_violations(
    relative: str, directory: Path, rows: Sequence[JsonObject], tokenizer: PromptTokenizer
) -> list[Violation]:
    problems = replay_problems(rows, tokenizer, directory.name)
    return [Violation(relative, 1, f"token replay: {item}") for item in problems[:SHOWN]]


def check_directory(
    root: Path, directory: Path, cases: dict[str, EvalCase], tokenizer: PromptTokenizer | None
) -> tuple[list[Violation], list[str]]:
    relative = directory.relative_to(root).as_posix()
    found = layout_violations(relative, directory)
    if found:
        return found, []
    texts = {
        name: (directory / name).read_text(encoding="utf-8")
        for name in (REPORT_FILE, TRANSCRIPTS_FILE)
    }
    for name, text in texts.items():
        found += secret_violations(f"{relative}/{name}", text)
    try:
        stored: Json = json.loads(texts[REPORT_FILE])
    except ValueError:
        return [*found, Violation(relative, 1, f"{REPORT_FILE} is not valid JSON")], []
    if not isinstance(stored, dict):
        return [*found, Violation(relative, 1, f"{REPORT_FILE} is not an object")], []
    regraded, rows = regrade_violations(relative, directory, stored, cases, root)
    found += identity_violations(relative, directory, stored, readable_rows(directory))
    found += regraded
    if tokenizer is None:
        return found, [f"token replay skipped for {relative}: no tokenizer"]
    stale = crossed_epoch(root, directory.parent.name, stored)
    if stale is not None:
        return found, [f"{CROSS_EPOCH} for {relative}: {stale}"]
    return [*found, *replay_violations(relative, directory, rows, tokenizer)], []


def report_directories(root: Path) -> list[Path]:
    base = root / REPORTS
    if not base.is_dir():
        return []
    return [
        mode
        for sha in sorted(base.iterdir())
        if sha.is_dir()
        for mode in sorted(sha.iterdir())
        if mode.is_dir()
    ]


def check(root: Path, tokenizer: PromptTokenizer | None) -> tuple[list[Violation], list[str]]:
    directories = report_directories(root)
    if not directories:
        return [], []
    loaded, problems = load_cases(root)
    if problems:
        return [Violation("eval/cases", 1, "cases do not load; run check_eval_cases.py")], []
    cases = {item.case.id: item.case for item in loaded}
    violations: list[Violation] = []
    notes: list[str] = []
    for directory in directories:
        found, skipped = check_directory(root, directory, cases, tokenizer)
        violations += found
        notes += skipped
    stale = sum(note.startswith(CROSS_EPOCH) for note in notes)
    if stale:
        notes.append(f"{CROSS_EPOCH}: {stale} of {len(directories)} reports; regrading still ran")
    return violations, notes


def load_tokenizer() -> PromptTokenizer | None:
    try:
        return PromptTokenizer.from_dir(load_config(os.environ).model_dir)
    except (TokenizerUnavailable, OSError, ValueError):
        return None


def main(argv: Sequence[str] | None = None) -> int:
    root = guardlib.parse_root(
        "Regrade committed eval reports and replay their token counts.", argv
    )
    violations, notes = check(root, load_tokenizer())
    for note in notes:
        sys.stderr.write(f"check_eval_reports: {note}\n")
    return guardlib.report(violations)


if __name__ == "__main__":
    sys.exit(main())
