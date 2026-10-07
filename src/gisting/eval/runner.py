import json
import os
import subprocess
import sys
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import get_args

from gisting.eval.applicability import write_record
from gisting.eval.baseline import Mode
from gisting.eval.case_files import LoadedCase, plan_orders
from gisting.eval.case_spec import EvalCase
from gisting.eval.redact import Redactor
from gisting.eval.slots import Filled, case_orders, fill_case

MODES: tuple[Mode, ...] = get_args(Mode)
AGENT_ARGUMENTS = ("run", "--batch", "--internal", "--transport", "local")
EMAIL_ARGUMENTS = ("-m", "gisting.shopify", "demo-emails")
TRANSCRIPTS_FILE = "transcripts.jsonl"
USAGE_EXIT = 2
MISSING_ROW = "missing_row"
STDERR_TAIL = 400


class RunFailed(RuntimeError):
    pass


@dataclass(frozen=True)
class Selection:
    splits: tuple[str, ...] = ("dev",)
    red_lines: tuple[str, ...] = ()
    families: tuple[str, ...] = ()
    per_red_line: int | None = None


@dataclass(frozen=True)
class Launched:
    lines: tuple[str, ...]
    returncode: int
    stderr: str


Launcher = Callable[[Sequence[str], str, Mapping[str, str]], Launched]


def subprocess_launcher(argv: Sequence[str], stdin: str, env: Mapping[str, str]) -> Launched:
    done = subprocess.run(
        list(argv), input=stdin, capture_output=True, text=True, env=dict(env), check=False
    )
    return Launched(tuple(done.stdout.splitlines()), done.returncode, done.stderr)


@dataclass(frozen=True)
class RunSpec:
    root: Path
    mode: str
    out: Path
    launch: Launcher = subprocess_launcher
    env: Mapping[str, str] | None = None
    env_file: Path | None = None
    fetch: Launcher = subprocess_launcher
    not_applicable: tuple[str, ...] = ()


@dataclass(frozen=True)
class RunResult:
    path: Path
    cases: int
    errors: int
    unknown_emails: int
    not_applicable: tuple[str, ...] = ()


def env_file_argv(env_file: Path | None) -> list[str]:
    return [] if env_file is None else ["--env-file", str(env_file)]


def agent_argv(mode: str, env_file: Path | None = None) -> list[str]:
    return [
        sys.executable,
        "-m",
        "gisting.agent",
        *AGENT_ARGUMENTS,
        "--mode",
        mode,
        *env_file_argv(env_file),
    ]


def parse_email_rows(lines: Sequence[str], orders: Sequence[str]) -> dict[str, str]:
    try:
        rows = [json.loads(line) for line in lines]
        emails = {row["order_number"]: row["email"] for row in rows}
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        message = "the email lookup printed a line that is not an order_number and email"
        raise RunFailed(message) from error
    if [row["order_number"] for row in rows] != list(orders):
        message = "the email lookup did not answer every order, in order"
        raise RunFailed(message)
    return emails


def stderr_tail(stderr: str) -> str:
    return Redactor({}).apply(stderr.strip()[-STDERR_TAIL:])


def fetch_emails(spec: RunSpec, orders: Sequence[str]) -> dict[str, str]:
    stdin = "".join(json.dumps({"order_number": order}) + "\n" for order in orders)
    argv = [sys.executable, *EMAIL_ARGUMENTS, *env_file_argv(spec.env_file)]
    launched = spec.fetch(argv, stdin, os.environ if spec.env is None else spec.env)
    if launched.returncode != 0:
        tail = stderr_tail(launched.stderr)
        message = f"the email lookup exited with {launched.returncode}: {tail}"
        raise RunFailed(message)
    return parse_email_rows(launched.lines, orders)


def select_cases(loaded: Sequence[LoadedCase], selection: Selection) -> list[EvalCase]:
    taken: dict[str, int] = defaultdict(int)
    chosen: list[EvalCase] = []
    for item in loaded:
        case = item.case
        wanted = (
            case.split in selection.splits
            and (not selection.red_lines or str(case.red_line) in selection.red_lines)
            and (not selection.families or case.family in selection.families)
        )
        limit = selection.per_red_line
        if wanted and (limit is None or taken[str(case.red_line)] < limit):
            taken[str(case.red_line)] += 1
            chosen.append(case)
    return chosen


@dataclass(frozen=True)
class Prepared:
    case: EvalCase
    filled: Filled


def plans_of(root: Path, cases: Sequence[EvalCase]) -> dict[str, list[str]]:
    plans: dict[str, list[str]] = {}
    for case in cases:
        name = case.fixtures.plan or ""
        if name not in plans:
            found = plan_orders(root, name)
            if found is None:
                message = f"case {case.id}: plan {name or '(none)'} is missing or unreadable"
                raise RunFailed(message)
            plans[name] = [item.order for item in found]
    return plans


def prepare(spec: RunSpec, cases: Sequence[EvalCase]) -> list[Prepared]:
    plans = plans_of(spec.root, cases)
    needed = {
        order
        for case in cases
        for order in case_orders(case, plans[case.fixtures.plan or ""]).values()
    }
    email_of = fetch_emails(spec, sorted(needed)) if needed else {}
    return [
        Prepared(case, fill_case(case, plans[case.fixtures.plan or ""], email_of)) for case in cases
    ]


def request_line(item: Prepared) -> str:
    return json.dumps(
        {"session_id": item.case.id, "messages": list(item.filled.messages)}, ensure_ascii=False
    )


def transcript_document(item: Prepared, mode: str, row: str | None) -> dict[str, object]:
    document: dict[str, object] = {"case_id": item.case.id, "mode": mode}
    parsed = json.loads(row) if row is not None else None
    if not isinstance(parsed, dict):
        error = {"type": MISSING_ROW, "message": "the agent printed no result for this request"}
        return {**document, "error": error}
    if "error" in parsed:
        return {**document, "error": parsed["error"]}
    return {**document, **parsed, "headers": {}, "cache_keys": []}


def transcript_lines(
    prepared: Sequence[Prepared], mode: str, rows: Sequence[str | None]
) -> tuple[list[str], int, int]:
    lines: list[str] = []
    errors = unknown = 0
    for item, row in zip(prepared, rows, strict=True):
        redactor = Redactor(item.filled.emails)
        document = transcript_document(item, mode, row)
        lines.append(redactor.apply(json.dumps(document, ensure_ascii=False, sort_keys=True)))
        errors += "error" in document
        unknown += redactor.unknown
    return lines, errors, unknown


def run_cases(spec: RunSpec, cases: Sequence[EvalCase]) -> RunResult:
    mode, out = spec.mode, spec.out
    prepared = prepare(spec, cases)
    stdin = "".join(request_line(item) + "\n" for item in prepared)
    launched = spec.launch(
        agent_argv(mode, spec.env_file), stdin, os.environ if spec.env is None else spec.env
    )
    if launched.returncode >= USAGE_EXIT:
        tail = stderr_tail(launched.stderr)
        message = f"the agent exited with {launched.returncode}: {tail}"
        raise RunFailed(message)
    if len(launched.lines) > len(prepared):
        message = f"the agent printed {len(launched.lines)} lines for {len(prepared)} requests"
        raise RunFailed(message)
    rows: list[str | None] = [*launched.lines, *[None] * (len(prepared) - len(launched.lines))]
    lines, errors, unknown = transcript_lines(prepared, mode, rows)
    out.mkdir(parents=True, exist_ok=True)
    path = out / TRANSCRIPTS_FILE
    path.write_text("".join(line + "\n" for line in lines), encoding="utf-8")
    write_record(out, spec.not_applicable)
    return RunResult(path, len(lines), errors, unknown, spec.not_applicable)
