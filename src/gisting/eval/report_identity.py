import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from gisting.eval.report import ReportError
from gisting.shopify.jsonvalue import Json, JsonObject

SHOWN = 3


@dataclass(frozen=True)
class IdentityProblem:
    field: str
    where: str
    found: Json
    expected: Json

    def describe(self) -> str:
        return f"{self.field} differs: {self.where} says {self.found!r}, expected {self.expected!r}"


class IdentityMismatch(ReportError):
    def __init__(self, problems: Sequence[IdentityProblem]) -> None:
        self.problems = tuple(problems)
        shown = "; ".join(item.describe() for item in self.problems[:SHOWN])
        more = len(self.problems) - SHOWN
        super().__init__(shown + (f"; {more} more" if more > 0 else ""))


def object_of(value: Json) -> JsonObject:
    return value if isinstance(value, dict) else {}


def usable_backend(value: Json) -> bool:
    return isinstance(value, str) and bool(value.strip())


def gist_problems(where: str, internal: JsonObject, mode: Json) -> list[IdentityProblem]:
    run_id = internal.get("gist_run_id")
    adapter = object_of(internal.get("model")).get("gist")
    if mode == "gist":
        found: list[IdentityProblem] = []
        if not isinstance(run_id, str) or not run_id.strip():
            found.append(IdentityProblem("gist_run_id", where, run_id, "a Gist run id"))
        if not isinstance(adapter, dict) or not adapter:
            found.append(IdentityProblem("model.gist", where, adapter, "the Gist adapter record"))
        return found
    if mode == "full":
        claims = (("gist_run_id", run_id), ("model.gist", adapter))
        return [
            IdentityProblem(n, where, got, "absent in full mode")
            for n, got in claims
            if got is not None
        ]
    return []


def row_problems(row: JsonObject, mode: Json, backend: Json) -> list[IdentityProblem]:
    where = f"transcripts.jsonl case {row.get('case_id')}"
    internal = object_of(row.get("internal"))
    claims: list[tuple[str, Json, Json]] = [("mode", internal.get("mode"), mode)]
    if "mode" in row:
        claims.append(("mode", row["mode"], mode))
    if usable_backend(backend):
        claims.append(("backend_id", internal.get("backend_id"), backend))
    found = [IdentityProblem(name, where, got, want) for name, got, want in claims if got != want]
    return found + gist_problems(where, internal, mode)


def identity_problems(
    directory: Path, report: JsonObject, rows: Sequence[JsonObject]
) -> list[IdentityProblem]:
    located = Path(os.path.abspath(directory))
    run = object_of(report.get("run"))
    tree, mode, backend = run.get("code_tree_sha"), run.get("mode"), run.get("backend_id")
    found: list[IdentityProblem] = []
    if tree != located.parent.name:
        found.append(IdentityProblem("code_tree_sha", "report.json", tree, located.parent.name))
    if mode != located.name:
        found.append(IdentityProblem("mode", "report.json", mode, located.name))
    if not usable_backend(backend):
        found.append(IdentityProblem("backend_id", "report.json", backend, "non-empty text"))
    answered = [row for row in rows if "error" not in row]
    if not answered:
        found.append(IdentityProblem("rows", "transcripts.jsonl", len(rows), "an answered row"))
    for row in answered:
        found += row_problems(row, mode, backend)
    return found


def require_identity(directory: Path, report: JsonObject, rows: Sequence[JsonObject]) -> None:
    problems = identity_problems(directory, report, rows)
    if problems:
        raise IdentityMismatch(problems)
