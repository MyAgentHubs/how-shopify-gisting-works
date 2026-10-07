import json
from dataclasses import replace
from pathlib import Path

import pytest
from fakes.model import FakeModel
from fakes.tiny_qwen import make_model_dir, tiny_model
from oracle import expected_output
from torch_support import HPARAMS, TOKENIZER, kit

from gisting.agent.policy import load_agent_policy
from gisting.model_server.config import ModelConfig
from gisting.shopify.jsonvalue import required_object, required_str
from gisting.training.cli import main
from gisting.training.dataset import build_dataset
from gisting.training.gist_run import Plan, run_training
from gisting.training.hparams import load_hparams
from gisting.training.samples import Sample, read_jsonl
from gisting.training.teacher import read_teacher, teach

POLICY = load_agent_policy()
SAMPLES = build_dataset()


def taught(directory: Path, samples: list[Sample], outputs: list[str]) -> Path:
    path = directory / "teacher.jsonl"
    teach(FakeModel(list(outputs)), kit(), samples, path)
    return path


@pytest.fixture(scope="module")
def oracle_teacher(tmp_path_factory: pytest.TempPathFactory) -> Path:
    directory = tmp_path_factory.mktemp("rehearsal")
    return taught(directory, SAMPLES, [expected_output(s) for s in SAMPLES])


def test_the_oracle_teacher_passes_the_raw_grader_on_every_sample(oracle_teacher: Path) -> None:
    bad = [
        (r.sample.id, r.verdict.problems) for r in read_teacher(oracle_teacher) if not r.verdict.ok
    ]
    assert bad == []


def test_the_oracle_teacher_also_passes_the_final_grader_on_every_sample(
    oracle_teacher: Path,
) -> None:
    bad = [
        (r.sample.id, r.verdict.problems)
        for r in read_teacher(oracle_teacher, "final")
        if not r.verdict.ok
    ]
    assert bad == []


@pytest.mark.parametrize("layer", ["decision", "raw", "final"])
def test_the_filter_command_keeps_every_oracle_row_on_both_layers(
    oracle_teacher: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str], layer: str
) -> None:
    out = tmp_path / f"{layer}.jsonl"
    capsys.readouterr()
    assert (
        main(["filter", "--teacher", str(oracle_teacher), "--out", str(out), "--layer", layer]) == 0
    )
    summary = json.loads(capsys.readouterr().out)
    assert summary["kept"] == len(SAMPLES)
    assert summary["rejected"] == 0
    assert summary["empty_groups"] == []
    assert len(list(read_jsonl(out))) == len(SAMPLES)


def test_the_filter_defaults_to_the_decision_layer(
    oracle_teacher: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    email_ask = POLICY.needs_input_replies["email"]
    ask = next(s for s in SAMPLES if expected_output(s) == email_ask)
    reworded = "Please provide the email address used for the order."
    path = taught(tmp_path, [ask], [reworded])
    out = tmp_path / "kept.jsonl"
    capsys.readouterr()
    assert main(["filter", "--teacher", str(path), "--out", str(out)]) == 0
    assert json.loads(capsys.readouterr().out)["kept"] == 1
    assert main(["filter", "--teacher", str(path), "--out", str(out), "--layer", "final"]) == 0
    final = json.loads(capsys.readouterr().out)
    assert final["kept"] == 0
    assert final["rejections"][0]["problems"][0] == "ask_lacks_example"


def test_the_whole_dataset_trains_a_gist_without_a_format_or_length_stop(
    oracle_teacher: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    filtered = tmp_path / "filtered.jsonl"
    assert main(["filter", "--teacher", str(oracle_teacher), "--out", str(filtered)]) == 0
    capsys.readouterr()
    config = ModelConfig(make_model_dir(tmp_path / "model"), "cpu")
    plan = Plan("rehearsal", config, filtered, tmp_path / "out", HPARAMS)
    summary = run_training(plan, tiny_model(), TOKENIZER)
    assert summary["skipped_too_long"] == []
    assert summary["train_examples"] == sum(1 for s in SAMPLES if s.split == "train")
    assert summary["dev_examples"] == sum(1 for s in SAMPLES if s.split == "dev")
    assert summary["base_params_unchanged"] is True


def test_the_shipped_hparams_train_the_same_path_with_checkpointing_on(
    oracle_teacher: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    shipped = load_hparams()
    assert shipped.gradient_checkpointing
    assert shipped.max_len == 2560
    kept = tmp_path / "filtered.jsonl"
    assert main(["filter", "--teacher", str(oracle_teacher), "--out", str(kept)]) == 0
    capsys.readouterr()
    rows = kept.read_text().splitlines()
    subset = tmp_path / "subset.jsonl"
    subset.write_text("\n".join(rows[::6]) + "\n")
    config = ModelConfig(make_model_dir(tmp_path / "model"), "cpu")
    hparams = replace(HPARAMS, gradient_checkpointing=shipped.gradient_checkpointing)
    summary = run_training(
        Plan("checkpointed", config, subset, tmp_path / "out", hparams), tiny_model(), TOKENIZER
    )
    assert summary["skipped_too_long"] == []
    assert summary["base_params_unchanged"] is True
    assert float(str(summary["dev_kl_end"])) < float(str(summary["dev_kl_start"]))


def test_an_ask_in_the_teachers_own_words_trains_as_it_is_with_no_template_swapped_in(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    email_ask = POLICY.needs_input_replies["email"]
    sample = next(s for s in SAMPLES if expected_output(s) == email_ask)
    reworded = "Please provide the email address used for the order."
    path = taught(tmp_path, [sample], [reworded])
    kept = tmp_path / "kept.jsonl"
    assert main(["filter", "--teacher", str(path), "--out", str(kept)]) == 0
    capsys.readouterr()
    (row,) = read_jsonl(kept)
    assert required_str(required_object(row, "teacher"), "text") == reworded
    (record,) = read_teacher(kept)
    assert record.text == reworded
    assert record.target_ids(kit())[: len(record.ids)] == list(record.ids)
    assert email_ask not in record.text
