import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from pathlib import Path

from gisting.eval.case import DECISION
from gisting.manifest.record import GistManifest
from gisting.prompt.messages import UserMessage
from gisting.shopify.jsonvalue import Json, JsonObject
from gisting.training.compare import MODES, Subject
from gisting.training.metrics import Outcome, mode_metrics, token_f1
from gisting.training.teacher import TeacherRecord

TRAINING_SUMMARY = "summary.json"
TRAINING_LOG = "training-log.jsonl"
SAMPLES_FILE = "samples.jsonl"
CURVES_FILE = "curves.json"
NOTES = (
    "Gisting imitates the Full-rules teacher; it cannot fix the teacher's own mistakes.",
    "Latency is recorded for the named backend only; no speed claim is made from it.",
    "judge fields are heuristic flags on the text, not a correctness grader.",
)


def question_of(record: TeacherRecord) -> str:
    users = [m.content for m in record.sample.messages if isinstance(m, UserMessage)]
    return users[-1] if users else ""


def row_of(mode: Outcome, teacher: Outcome) -> JsonObject:
    return {
        "text": mode.text,
        "exact": mode.text == teacher.text,
        "token_f1": round(token_f1(mode.ids, teacher.ids), 4),
        "tool_calls": len(mode.parsed.calls),
        "judge_ok": mode.verdict.ok,
        "judge_problems": list(mode.verdict.problems),
    }


def sample_rows(
    records: Sequence[TeacherRecord], teacher: Sequence[Outcome], modes: Mapping[str, list[Outcome]]
) -> list[JsonObject]:
    rows: list[JsonObject] = []
    for index, record in enumerate(records):
        sample = record.sample
        row: JsonObject = {
            "id": sample.id,
            "kind": sample.kind,
            "category": sample.category,
            "family": sample.family,
            "scenario": sample.scenario,
            "question": question_of(record),
            "teacher": {
                "text": teacher[index].text,
                "tool_calls": len(teacher[index].parsed.calls),
                "judge_ok": teacher[index].verdict.ok,
                "judge_problems": list(teacher[index].verdict.problems),
            },
        }
        for mode in MODES:
            row[mode] = row_of(modes[mode][index], teacher[index])
        rows.append(row)
    return rows


def build_report(
    subject: Subject,
    records: Sequence[TeacherRecord],
    teacher: Sequence[Outcome],
    modes: Mapping[str, list[Outcome]],
    gist_dir: Path,
) -> JsonObject:
    summary_path = gist_dir / TRAINING_SUMMARY
    summary: JsonObject = json.loads(summary_path.read_text()) if summary_path.exists() else {}
    manifest: GistManifest = subject.manifest
    notes: list[Json] = list(NOTES)
    samples: list[Json] = list(sample_rows(records, teacher, modes))
    return {
        "run_id": manifest.run_id,
        "backend_id": subject.model.backend_id,
        "split": "dev",
        "grading_layer": DECISION,
        "dev_samples": len(records),
        "manifest": asdict(manifest),
        "hparams": asdict(subject.hparams),
        "training": summary,
        "teacher": mode_metrics(teacher, teacher),
        "modes": {mode: mode_metrics(modes[mode], teacher) for mode in MODES},
        "notes": notes,
        "samples": samples,
    }


def curves_of(gist_dir: Path) -> JsonObject:
    log = gist_dir / TRAINING_LOG
    rows: list[JsonObject] = [json.loads(line) for line in log.read_text().splitlines()]
    steps: list[Json] = [row for row in rows if row["event"] == "step"]
    dev: list[Json] = [row for row in rows if row["event"] == "dev"]
    return {"steps": steps, "dev": dev}


def write_outputs(report: JsonObject, gist_dir: Path, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    samples = report["samples"]
    rows = samples if isinstance(samples, list) else []
    lines = (json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows)
    (out.parent / SAMPLES_FILE).write_text("".join(lines), encoding="utf-8")
    curves = json.dumps(curves_of(gist_dir), indent=2) + "\n"
    (out.parent / CURVES_FILE).write_text(curves, encoding="utf-8")
