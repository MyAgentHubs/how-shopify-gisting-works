import json
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TextIO

from gisting.agent.state import AgentDeps
from gisting.agent.turn import run_turn
from gisting.agent.wire import parse_request, wire
from gisting.shopify.demo_apply import UsageError

INVALID_REQUEST = "invalid_request"
TURN_ERROR = "turn_error"
FAILED_EXIT = 1
ROW_ERRORS = (ValueError, OSError, RuntimeError)


@dataclass(frozen=True)
class Row:
    text: str
    problem: str | None = None


def error_row(kind: str, message: str) -> Row:
    document = {"error": {"type": kind, "message": message}}
    return Row(json.dumps(document, sort_keys=True), kind)


def answer_row(deps: AgentDeps, text: str, *, internal: bool) -> Row:
    try:
        session_id, messages = parse_request(json.loads(text))
    except RecursionError:
        return error_row(INVALID_REQUEST, "request JSON is nested too deeply")
    except (ValueError, UsageError) as error:
        return error_row(INVALID_REQUEST, str(error))
    try:
        result = run_turn(deps, session_id, messages)
    except ROW_ERRORS as error:
        return error_row(TURN_ERROR, f"{type(error).__name__}: {error}")
    reason = result.fallback_reason
    return Row(wire(result, internal=internal), None if reason is None else reason.value)


def run_batch(deps: AgentDeps, lines: Iterable[str], out: TextIO, *, internal: bool) -> int:
    failed = 0
    for number, text in enumerate(lines, start=1):
        row = answer_row(deps, text, internal=internal)
        out.write(row.text + "\n")
        out.flush()
        if row.problem is not None:
            failed += 1
            sys.stderr.write(f"gisting.agent: row {number}: {row.problem}\n")
    return FAILED_EXIT if failed else 0
