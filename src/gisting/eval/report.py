import hashlib
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from gisting.eval.applicability import record_problems, section_of
from gisting.eval.canary import TranscriptError, transcript_from_json
from gisting.eval.case import FINAL, RAW
from gisting.eval.case_files import load_cases
from gisting.eval.case_spec import EvalCase
from gisting.eval.judging import Judges, Outcome, Outcomes
from gisting.eval.registry import Metric, load_registry
from gisting.eval.report_tokens import as_object, token_metrics
from gisting.eval.stats import upper_bound
from gisting.prompt.fingerprint import rules_sha256
from gisting.shopify.jsonvalue import Json, JsonObject

REPORT_VERSION = 1
RULES_VERSION_CHARS = 16
POLICY_FILE = ("prompts", "agent_policy.json")
LAYER_ORDER = (RAW, FINAL)
IDENTITY_KEYS = ("backend_id", "mode", "gist_run_id")
SHOWN_CASES = 3


class ReportError(ValueError):
    pass


class IncompleteRun(ReportError):
    def __init__(self, reason: str, detail: str, case_ids: Sequence[str] = ()) -> None:
        self.reason = reason
        self.case_ids = tuple(case_ids)
        super().__init__(f"{reason}: {detail}")


@dataclass(frozen=True)
class Graded:
    case: EvalCase
    row: JsonObject
    outcomes: Outcomes


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_rows(path: Path) -> list[JsonObject]:
    rows: list[JsonObject] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        document: Json = json.loads(line)
        if not isinstance(document, dict) or not isinstance(document.get("case_id"), str):
            message = f"{path.name} line {number}: not a transcript row"
            raise ReportError(message)
        rows.append(document)
    return rows


def case_map(root: Path) -> dict[str, EvalCase]:
    loaded, problems = load_cases(root)
    if problems:
        message = f"{len(problems)} case file problems; run scripts/check_eval_cases.py"
        raise ReportError(message)
    return {item.case.id: item.case for item in loaded}


def grade_rows(
    rows: Sequence[JsonObject], cases: Mapping[str, EvalCase], judges: Judges
) -> tuple[list[Graded], list[str]]:
    graded: list[Graded] = []
    errors: list[str] = []
    for row in rows:
        case_id = str(row["case_id"])
        case = cases.get(case_id)
        if case is None:
            message = f"transcript for unknown case {case_id}"
            raise ReportError(message)
        if "error" in row:
            errors.append(case_id)
            continue
        try:
            transcript = transcript_from_json(row)
        except TranscriptError as error:
            message = f"case {case_id}: {error}"
            raise ReportError(message) from error
        graded.append(Graded(case, row, judges.judge_case(case, transcript, row)))
    return graded, errors


def require_complete(
    report: JsonObject, rows: Sequence[JsonObject], graded: Sequence[Graded], errors: Sequence[str]
) -> None:
    repeated = sorted(
        case for case, count in Counter(str(row["case_id"]) for row in rows).items() if count > 1
    )
    if repeated:
        detail = (
            f"{len(repeated)} cases have more than one row ({', '.join(repeated[:SHOWN_CASES])})"
        )
        raise IncompleteRun("duplicate_rows", detail, repeated)
    if errors:
        shown = ", ".join(sorted(errors)[:SHOWN_CASES])
        detail = f"{len(errors)} transcript rows are error rows ({shown})"
        raise IncompleteRun("error_rows", detail, errors)
    cases = as_object(report.get("cases"))
    claimed = (cases.get("transcripts"), cases.get("graded"))
    if len(graded) != len(rows) or claimed != (len(rows), len(graded)):
        detail = f"{len(rows)} rows and {len(graded)} graded, the report counts {claimed}"
        raise IncompleteRun("counts", detail)


def layer_entry(items: Sequence[tuple[Graded, Outcome]]) -> JsonObject:
    failed = sorted((graded.case.id, outcome) for graded, outcome in items if outcome.failed)
    n = len(items)
    categories = Counter(graded.case.category for graded, outcome in items if outcome.failed)
    details: list[Json] = [{"case": case, "problems": [*o.problems]} for case, o in failed]
    by_category: JsonObject = {name: count for name, count in sorted(categories.items())}
    return {
        "failures": len(failed),
        "n": n,
        "rate": round(len(failed) / n, 6) if n else None,
        "upper95": round(upper_bound(len(failed), n), 6),
        "failed_cases": details,
        "by_category": by_category,
    }


def metric_entry(metric: Metric, graded: Sequence[Graded]) -> JsonObject:
    layers: JsonObject = {}
    n = 0
    for layer in LAYER_ORDER:
        items = [
            (g, g.outcomes[metric.name, layer])
            for g in graded
            if (metric.name, layer) in g.outcomes
        ]
        if items:
            layers[layer] = layer_entry(items)
            n = len(items)
    enough = None if metric.min_cases is None else n >= metric.min_cases
    return {
        "gate": metric.gate,
        "tolerance": metric.tolerance,
        "min_cases": metric.min_cases,
        "enough_cases": enough,
        "layers": layers,
    }


def one_value(rows: Sequence[JsonObject], key: str) -> Json:
    values = {json.dumps(as_object(row.get("internal")).get(key), sort_keys=True) for row in rows}
    if len(values) > 1:
        message = f"transcripts disagree on {key}: {sorted(values)}"
        raise ReportError(message)
    return json.loads(values.pop()) if values else None


def max_new_tokens(root: Path) -> int | None:
    document: Json = json.loads(root.joinpath(*POLICY_FILE).read_text(encoding="utf-8"))
    value = document.get("max_new_tokens") if isinstance(document, dict) else None
    return value if isinstance(value, int) else None


def run_section(rows: Sequence[JsonObject], root: Path, code_tree_sha: str) -> JsonObject:
    answered = [row for row in rows if "error" not in row]
    section: JsonObject = {
        "code_tree_sha": code_tree_sha,
        "rules_version": rules_sha256()[:RULES_VERSION_CHARS],
        "decoding": {"sampling": "greedy", "max_new_tokens": max_new_tokens(root)},
        "model": one_value(answered, "model"),
    }
    for key in IDENTITY_KEYS:
        section[key] = one_value(answered, key)
    return section


def with_not_applicable(
    report: JsonObject,
    record: JsonObject | None,
    rows: Sequence[JsonObject],
    cases: Mapping[str, EvalCase],
) -> JsonObject:
    if record is None:
        return report
    problems = record_problems(record, cases, {str(row["case_id"]) for row in rows})
    if problems:
        message = f"not applicable record: {problems[0]}"
        raise ReportError(message)
    summary = report["cases"]
    if not isinstance(summary, dict):
        message = "report has no cases section"
        raise ReportError(message)
    return {**report, "cases": {**summary, "not_applicable": section_of(record)}}


def build_report(
    rows: Sequence[JsonObject],
    cases: Mapping[str, EvalCase],
    root: Path,
    code_tree_sha: str,
    transcripts_text: str,
) -> JsonObject:
    metrics, problems = load_registry(root / "eval" / "metrics.toml")
    if problems:
        message = f"eval/metrics.toml: {problems[0]}"
        raise ReportError(message)
    graded, errors = grade_rows(rows, cases, Judges(root))
    run = run_section(rows, root, code_tree_sha)
    names = {name for item in graded for name, _layer in item.outcomes}
    by_line = Counter(str(item.case.red_line) for item in graded)
    summary: JsonObject = {
        "transcripts": len(rows),
        "graded": len(graded),
        "run_errors": [*sorted(errors)],
        "complete": not errors,
        "by_red_line": {line: count for line, count in sorted(by_line.items())},
        "splits": [*sorted({item.case.split for item in graded})],
        "transcripts_sha256": sha256_text(transcripts_text),
    }
    return {
        "version": REPORT_VERSION,
        "run": run,
        "cases": summary,
        "metrics": {m.name: metric_entry(m, graded) for m in metrics if m.name in names},
        "tokens": token_metrics([item.row for item in graded], str(run["mode"])),
    }
