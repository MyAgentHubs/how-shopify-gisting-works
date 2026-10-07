import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from gisting.eval.case import RAW, Verdict
from gisting.eval.data import load_grader_data
from gisting.eval.data_model import GraderData
from gisting.eval.grade import grade
from gisting.model_server.interface import Model
from gisting.prompt.parse import parse_output
from gisting.prompt.tokenizer import IM_END
from gisting.shopify.jsonvalue import (
    Json,
    JsonObject,
    required_list,
    required_object,
    required_str,
)
from gisting.training.kit import Kit
from gisting.training.samples import (
    Sample,
    dump_jsonl,
    read_jsonl,
    sample_from_json,
    sample_json,
)

STOPPED = "stop"
MS_DIGITS = 1


@dataclass(frozen=True)
class TeacherRecord:
    sample: Sample
    ids: tuple[int, ...]
    text: str
    finish_reason: str
    verdict: Verdict
    backend_id: str
    first_token_ms: float
    total_ms: float

    def target_ids(self, kit: Kit) -> list[int]:
        stop = [kit.tokenizer.control(IM_END)] if self.finish_reason == STOPPED else []
        return [*self.ids, *stop]


def teach_one(model: Model, kit: Kit, sample: Sample, data: GraderData) -> JsonObject:
    prompt = kit.prompt(sample.messages, gist=False)
    result = model.generate(prompt.ids, kit.max_new_tokens)
    verdict = grade(sample.case, parse_output(result.text), data)
    ids: list[Json] = list(result.ids)
    problems: list[Json] = list(verdict.problems)
    teacher: JsonObject = {
        "ids": ids,
        "text": result.text,
        "finish_reason": result.finish_reason,
        "first_token_ms": round(result.first_token_ms, MS_DIGITS),
        "total_ms": round(result.total_ms, MS_DIGITS),
        "backend_id": model.backend_id,
        "prompt_tokens": cast(Json, prompt.stats.as_json()),
    }
    return {
        "sample": sample_json(sample),
        "teacher": teacher,
        "verdict": {"ok": verdict.ok, "problems": problems},
    }


def parse_record(row: JsonObject, data: GraderData, layer: str = RAW) -> TeacherRecord:
    teacher = required_object(row, "teacher")
    ids = tuple(item for item in required_list(teacher, "ids") if isinstance(item, int))
    sample = sample_from_json(required_object(row, "sample"))
    text = required_str(teacher, "text")
    return TeacherRecord(
        sample=sample,
        ids=ids,
        text=text,
        finish_reason=required_str(teacher, "finish_reason"),
        verdict=grade(sample.case, parse_output(text), data, layer),
        backend_id=required_str(teacher, "backend_id"),
        first_token_ms=float(str(teacher["first_token_ms"])),
        total_ms=float(str(teacher["total_ms"])),
    )


def read_teacher(path: Path, layer: str = RAW) -> list[TeacherRecord]:
    data = load_grader_data()
    return [parse_record(row, data, layer) for row in read_jsonl(path)]


def teach(model: Model, kit: Kit, samples: Iterable[Sample], out: Path) -> int:
    data = load_grader_data()
    done = {record.sample.id for record in read_teacher(out)} if out.exists() else set()
    written = 0
    for sample in samples:
        if sample.id in done:
            continue
        row = teach_one(model, kit, sample, data)
        with out.open("a", encoding="utf-8") as handle:
            handle.write(dump_jsonl([row]))
        written += 1
        sys.stderr.write(f"gisting.training: taught {sample.id} ({written})\n")
    return written
