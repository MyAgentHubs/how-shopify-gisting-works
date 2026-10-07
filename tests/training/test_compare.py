import json
from pathlib import Path

import pytest
from fakes.tiny_qwen import K, torch
from torch_support import HPARAMS, TOKENIZER, kit, plan_for

from gisting.manifest.record import read_manifest
from gisting.model_server.gist_store import read_gist
from gisting.model_server.transformers_backend import TransformersModel
from gisting.training.compare import (
    MODES,
    CompareMismatch,
    Subject,
    check_provenance,
    run_mode,
    teacher_outcomes,
)
from gisting.training.gist_init import chunk_mean_init
from gisting.training.gist_run import run_training
from gisting.training.metrics import Outcome
from gisting.training.report import build_report
from gisting.training.teacher import TeacherRecord, read_teacher


def trained_subject(tmp_path: Path) -> tuple[Subject, list[TeacherRecord], Path, Path]:
    plan, model = plan_for(tmp_path)
    run_training(plan, model, TOKENIZER)
    manifest = read_manifest(plan.out_dir)
    model.attach_gist(plan.out_dir, plan.config.model_dir)
    assert model.gist is not None
    subject = Subject(model, kit(), manifest, HPARAMS, model.gist)
    records = [r for r in read_teacher(plan.teacher_file) if r.sample.split == "dev"]
    return subject, records, plan.teacher_file, plan.out_dir


def test_each_mode_uses_its_own_rules_segment_and_leaves_the_model_state_reusable(
    tmp_path: Path,
) -> None:
    subject, records, _, _ = trained_subject(tmp_path)
    modes = {mode: run_mode(subject, records, mode) for mode in MODES}
    assert len(records) == 3
    full = modes["full"][0].prompt_tokens
    gist = modes["trained_gist"][0].prompt_tokens
    assert modes["untrained_gist"][0].prompt_tokens == gist
    assert full["rules"] - gist["rules"] == len(kit().full.ids) - K
    assert (full["tools"], full["history"]) == (gist["tools"], gist["history"])


def test_untrained_mode_injects_the_chunk_mean_initialisation(tmp_path: Path) -> None:
    from compare_support import injected_vectors

    subject, _, _, out_dir = trained_subject(tmp_path)
    untrained = injected_vectors(subject, "untrained_gist")
    assert torch.equal(untrained, chunk_mean_init(subject.model.network, subject.kit, K))
    assert injected_vectors(subject, "full") is None
    assert torch.equal(injected_vectors(subject, "trained_gist"), read_gist(out_dir))


def test_full_mode_reproduces_the_cached_teacher_exactly(tmp_path: Path) -> None:
    subject, records, _, _ = trained_subject(tmp_path)
    again = run_mode(subject, records, "full")
    cached = teacher_outcomes(records, subject.kit)
    assert [o.prompt_tokens for o in again] == [o.prompt_tokens for o in cached]


def test_provenance_check_refuses_another_teacher_file_or_hparams(tmp_path: Path) -> None:
    subject, _, teacher_file, _ = trained_subject(tmp_path)
    check_provenance(subject.manifest, teacher_file)
    teacher_file.write_text(teacher_file.read_text() + "\n")
    with pytest.raises(CompareMismatch, match="teacher file"):
        check_provenance(subject.manifest, teacher_file)


def test_report_is_strict_json_with_all_three_modes_and_raw_samples(tmp_path: Path) -> None:
    subject, records, _, out_dir = trained_subject(tmp_path)
    modes: dict[str, list[Outcome]] = {m: run_mode(subject, records, m) for m in MODES}
    report = build_report(subject, records, teacher_outcomes(records, subject.kit), modes, out_dir)
    document = json.loads(json.dumps(report, allow_nan=False))
    assert document["run_id"] == "run-test"
    assert document["backend_id"] == "transformers-cpu-float32"
    assert document["manifest"]["k"] == K
    assert set(document["modes"]) == set(MODES)
    assert document["training"]["base_params_unchanged"] is True
    assert len(document["samples"]) == 3
    assert set(document["samples"][0]) >= {"question", "teacher", *MODES}
    assert isinstance(subject.model, TransformersModel)


def test_every_verdict_in_the_comparison_is_graded_on_the_decision_layer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gisting.eval.case import DECISION, Case, Verdict
    from gisting.eval.data_model import GraderData
    from gisting.prompt.parse import ParsedOutput
    from gisting.training import compare

    seen: list[str] = []
    real = compare.grade

    def spy(case: Case, parsed: ParsedOutput, data: GraderData, layer: str = "raw") -> Verdict:
        seen.append(layer)
        return real(case, parsed, data, layer)

    monkeypatch.setattr(compare, "grade", spy)
    subject, records, _, out_dir = trained_subject(tmp_path)
    modes = {m: run_mode(subject, records, m) for m in MODES}
    report = build_report(subject, records, teacher_outcomes(records, subject.kit), modes, out_dir)
    assert seen
    assert set(seen) == {DECISION}
    assert report["grading_layer"] == DECISION
