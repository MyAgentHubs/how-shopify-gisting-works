import json
from dataclasses import replace
from pathlib import Path

import pytest
from fakes.tiny_qwen import tiny_model, torch
from torch_support import HPARAMS, TOKENIZER, kit, pick, plan_for

from gisting.manifest.record import GIST_FILE, read_manifest, sha256_file
from gisting.manifest.verify import ManifestMismatch
from gisting.model_server.gist import GistInjection
from gisting.model_server.gist_store import read_gist
from gisting.training.gist_run import LOG_FILE, SUMMARY_FILE, ArtifactDirectoryUsed, run_training
from gisting.training.hparams import hparams_sha256


def test_training_run_writes_a_manifested_artifact_and_leaves_the_base_untouched(
    tmp_path: Path,
) -> None:
    plan, model = plan_for(tmp_path)
    summary = run_training(plan, model, TOKENIZER)
    assert summary["base_params_unchanged"] is True
    assert summary["base_params_sha256_before"] == summary["base_params_sha256_after"]
    assert summary["train_examples"] == 6
    assert summary["dev_examples"] == 3
    assert summary["steps"] == 3 * HPARAMS.epochs
    manifest = read_manifest(plan.out_dir)
    assert manifest.run_id == "run-test"
    assert manifest.k == HPARAMS.k
    assert manifest.dataset_sha256 == sha256_file(plan.teacher_file)
    assert manifest.train_config_sha256 == hparams_sha256()
    assert manifest.backend_id == model.backend_id
    assert manifest.placeholder_id == TOKENIZER.gist_placeholder
    assert manifest.gist_sha256 == sha256_file(plan.out_dir / GIST_FILE)
    log = [json.loads(line) for line in (plan.out_dir / LOG_FILE).read_text().splitlines()]
    assert [row["event"] for row in log].count("dev") == HPARAMS.epochs + 1
    assert json.loads((plan.out_dir / SUMMARY_FILE).read_text())["run_id"] == "run-test"


def test_the_trained_artifact_loads_into_a_serving_model_and_generates(tmp_path: Path) -> None:
    plan, model = plan_for(tmp_path)
    run_training(plan, model, TOKENIZER)
    served = tiny_model()
    served.attach_gist(plan.out_dir, plan.config.model_dir)
    saved = read_gist(plan.out_dir)
    assert served.gist is not None
    assert torch.equal(served.gist.vectors.cpu(), saved)
    prefix = kit().prompt(pick("dev", 1)[0].messages, gist=True).ids
    reference = tiny_model(GistInjection(saved, TOKENIZER.gist_placeholder))
    assert served.generate(prefix, 5).ids == reference.generate(prefix, 5).ids


def test_a_run_directory_that_holds_an_artifact_is_refused(tmp_path: Path) -> None:
    plan, model = plan_for(tmp_path)
    plan.out_dir.mkdir()
    (plan.out_dir / GIST_FILE).write_text("x")
    with pytest.raises(ArtifactDirectoryUsed):
        run_training(plan, model, TOKENIZER)


def test_a_run_directory_may_already_hold_its_input_files(tmp_path: Path) -> None:
    plan, model = plan_for(tmp_path)
    plan.out_dir.mkdir()
    (plan.out_dir / "teacher.jsonl").write_text("x")
    assert run_training(plan, model, TOKENIZER)["base_params_unchanged"] is True


def test_the_artifact_is_refused_by_a_model_with_a_changed_base(tmp_path: Path) -> None:
    plan, model = plan_for(tmp_path)
    run_training(plan, model, TOKENIZER)
    (plan.config.model_dir / "SHA256SUMS").write_text("1" * 64 + "  other\n")
    with pytest.raises(ManifestMismatch, match="base_model_sha256"):
        tiny_model().attach_gist(plan.out_dir, plan.config.model_dir)


def test_random_init_runs_too(tmp_path: Path) -> None:
    plan, model = plan_for(tmp_path, replace(HPARAMS, init="random", epochs=1))
    summary = run_training(plan, model, TOKENIZER)
    assert summary["init"] == "random"
    assert summary["base_params_unchanged"] is True
