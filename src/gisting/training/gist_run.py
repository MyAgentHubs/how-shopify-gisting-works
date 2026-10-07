import json
import time
from dataclasses import dataclass
from pathlib import Path

import torch

from gisting.manifest.record import GIST_FILE, MANIFEST_FILE, sha256_file
from gisting.model_server.config import ModelConfig
from gisting.model_server.gist import parameters_sha256
from gisting.model_server.transformers_backend import TransformersModel
from gisting.prompt.tokenizer import PromptTokenizer
from gisting.shopify.jsonvalue import Json, JsonObject
from gisting.training.artifact import Provenance, write_artifact
from gisting.training.examples import Example, make_example
from gisting.training.gist_init import initial_gist
from gisting.training.hparams import Hparams, hparams_sha256
from gisting.training.kit import Kit, make_kit
from gisting.training.samples import dump_jsonl
from gisting.training.teacher import read_teacher
from gisting.training.trainer import Run, train

LOG_FILE = "training-log.jsonl"
SUMMARY_FILE = "summary.json"


class ArtifactDirectoryUsed(ValueError):
    pass


@dataclass(frozen=True)
class Plan:
    run_id: str
    config: ModelConfig
    teacher_file: Path
    out_dir: Path
    hparams: Hparams


def examples_for(kit: Kit, teacher_file: Path, model: TransformersModel, max_len: int):
    device = str(model.network.device)
    train_set: list[Example] = []
    dev_set: list[Example] = []
    skipped: list[Json] = []
    for record in read_teacher(teacher_file):
        example = make_example(kit, record, device, max_len)
        if example is None:
            skipped.append(record.sample.id)
        else:
            (train_set if record.sample.split == "train" else dev_set).append(example)
    return train_set, dev_set, skipped


def prepare_directory(out_dir: Path) -> None:
    if any((out_dir / name).exists() for name in (GIST_FILE, MANIFEST_FILE, SUMMARY_FILE)):
        message = f"{out_dir} already holds a Gist artifact; pick a new run id"
        raise ArtifactDirectoryUsed(message)
    out_dir.mkdir(parents=True, exist_ok=True)


def summarize(run: Run, plan: Plan, extra: JsonObject) -> JsonObject:
    devs = [row for row in run.log if row["event"] == "dev"]
    steps = [row for row in run.log if row["event"] == "step"]
    return {
        "run_id": plan.run_id,
        "init": plan.hparams.init,
        "dev_kl_start": devs[0]["dev_kl"],
        "dev_kl_end": devs[-1]["dev_kl"],
        "dev_kl_by_epoch": [row["dev_kl"] for row in devs],
        "loss_first_step": steps[0]["loss"],
        "loss_last_step": steps[-1]["loss"],
        "steps": len(steps),
        **extra,
    }


def run_training(plan: Plan, model: TransformersModel, tokenizer: PromptTokenizer) -> JsonObject:
    hp = plan.hparams
    prepare_directory(plan.out_dir)
    torch.manual_seed(hp.seed)
    kit = make_kit(tokenizer, hp.k)
    train_set, dev_set, skipped = examples_for(kit, plan.teacher_file, model, hp.max_len)
    for parameter in model.network.parameters():
        parameter.requires_grad_(False)
    before = parameters_sha256(model.network)
    start = initial_gist(model.network, kit, hp.init, hp.seed, hp.k)
    run = Run(model.network, tokenizer.gist_placeholder, hp, torch.nn.Parameter(start.clone()))
    started = time.monotonic()
    train(run, train_set, dev_set)
    after = parameters_sha256(model.network)
    if before != after:
        message = "base model parameters changed during Gist training"
        raise AssertionError(message)
    origin = Provenance(
        plan.run_id,
        plan.config.model_dir,
        model.backend_id,
        hparams_sha256(),
        sha256_file(plan.teacher_file),
    )
    write_artifact(plan.out_dir, run.gist.detach(), tokenizer, origin)
    extra: JsonObject = {
        "train_examples": len(train_set),
        "dev_examples": len(dev_set),
        "skipped_too_long": skipped,
        "base_params_sha256_before": before,
        "base_params_sha256_after": after,
        "base_params_unchanged": before == after,
        "backend_id": model.backend_id,
        "train_seconds": round(time.monotonic() - started, 1),
    }
    summary = summarize(run, plan, extra)
    (plan.out_dir / LOG_FILE).write_text(dump_jsonl(run.log), encoding="utf-8")
    (plan.out_dir / SUMMARY_FILE).write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary
