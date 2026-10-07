from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from gisting.eval.case import DECISION
from gisting.eval.data import load_grader_data
from gisting.eval.data_model import GraderData
from gisting.eval.grade import grade
from gisting.manifest.record import GistManifest, sha256_file
from gisting.model_server.gist import GistInjection
from gisting.model_server.transformers_backend import TransformersModel
from gisting.prompt.parse import parse_output
from gisting.training.gist_init import initial_gist
from gisting.training.hparams import Hparams, hparams_sha256
from gisting.training.kit import Kit
from gisting.training.metrics import Outcome
from gisting.training.teacher import TeacherRecord

MODES = ("full", "untrained_gist", "trained_gist")


class CompareMismatch(ValueError):
    pass


@dataclass(frozen=True)
class Subject:
    model: TransformersModel
    kit: Kit
    manifest: GistManifest
    hparams: Hparams
    trained: GistInjection


def check_provenance(manifest: GistManifest, teacher_file: Path) -> None:
    found: list[str] = []
    if manifest.dataset_sha256 != sha256_file(teacher_file):
        found.append("teacher file differs from the one the Gist was trained on")
    if manifest.train_config_sha256 != hparams_sha256():
        found.append("data/gist/hparams.json changed since the Gist was trained")
    if found:
        raise CompareMismatch("; ".join(found))


def outcome_of(record: TeacherRecord, kit: Kit, data: GraderData) -> Outcome:
    stats = kit.prompt(record.sample.messages, gist=False).stats.as_json()
    parsed = parse_output(record.text)
    return Outcome(
        record.sample.id,
        record.sample.kind,
        record.sample.category,
        record.text,
        record.ids,
        parsed,
        grade(record.sample.case, parsed, data, DECISION),
        stats,
        record.first_token_ms,
        record.total_ms,
    )


def teacher_outcomes(records: Sequence[TeacherRecord], kit: Kit) -> list[Outcome]:
    data = load_grader_data()
    return [outcome_of(record, kit, data) for record in records]


def run_mode(subject: Subject, records: Sequence[TeacherRecord], mode: str) -> list[Outcome]:
    model, kit = subject.model, subject.kit
    model.gist = mode_injection(subject, mode)
    data = load_grader_data()
    outcomes: list[Outcome] = []
    for record in records:
        prompt = kit.prompt(record.sample.messages, gist=mode != "full")
        result = model.generate(prompt.ids, kit.max_new_tokens)
        parsed = parse_output(result.text)
        outcomes.append(
            Outcome(
                record.sample.id,
                record.sample.kind,
                record.sample.category,
                result.text,
                result.ids,
                parsed,
                grade(record.sample.case, parsed, data, DECISION),
                prompt.stats.as_json(),
                result.first_token_ms,
                result.total_ms,
            )
        )
    return outcomes


def mode_injection(subject: Subject, mode: str) -> GistInjection | None:
    if mode == "full":
        return None
    if mode == "trained_gist":
        return subject.trained
    hp = subject.hparams
    start = initial_gist(subject.model.network, subject.kit, hp.init, hp.seed, hp.k)
    return GistInjection(start.detach(), subject.trained.placeholder_id)
