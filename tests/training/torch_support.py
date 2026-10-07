from pathlib import Path

from fakes.model import FakeModel
from fakes.tiny_qwen import K, make_model_dir, tiny_model, torch
from fakes.tokenizer import synthetic_prompt_tokenizer

from gisting.eval.case import Verdict
from gisting.model_server.config import ModelConfig
from gisting.model_server.transformers_backend import TransformersModel
from gisting.training.dataset import build_dataset
from gisting.training.examples import Example, make_example
from gisting.training.gist_init import initial_gist
from gisting.training.gist_run import Plan
from gisting.training.hparams import Hparams
from gisting.training.kit import Kit, make_kit
from gisting.training.samples import Sample
from gisting.training.teacher import TeacherRecord, teach
from gisting.training.trainer import Run

HPARAMS = Hparams(K, 7, 0.05, 2, 2, 8192, 1.0, "chunk_mean", False)
TOKENIZER = synthetic_prompt_tokenizer()


def kit() -> Kit:
    return make_kit(TOKENIZER, K)


def pick(split: str, count: int) -> list[Sample]:
    return [s for s in build_dataset() if s.split == split][:count]


def record(sample: Sample, ids: tuple[int, ...] = (11, 12, 13)) -> TeacherRecord:
    return TeacherRecord(sample, ids, "x", "stop", Verdict(True, ()), "t", 1.0, 2.0)


def examples(split: str, count: int) -> list[Example]:
    built = [make_example(kit(), record(s), "cpu", 8192) for s in pick(split, count)]
    return [item for item in built if item is not None]


def fresh_run(model: TransformersModel, hparams: Hparams = HPARAMS) -> Run:
    for parameter in model.network.parameters():
        parameter.requires_grad_(False)
    start = initial_gist(model.network, kit(), hparams.init, hparams.seed, hparams.k)
    gist = torch.nn.Parameter(start.clone())
    return Run(model.network, TOKENIZER.gist_placeholder, hparams, gist)


def plan_for(directory: Path, hparams: Hparams = HPARAMS) -> tuple[Plan, TransformersModel]:
    model_dir = make_model_dir(directory / "model")
    samples = pick("train", 6) + pick("dev", 3)
    teacher = directory / "teacher.jsonl"
    teach(FakeModel(["ok"] * len(samples)), kit(), samples, teacher)
    config = ModelConfig(model_dir, "cpu")
    return Plan("run-test", config, teacher, directory / "out", hparams), tiny_model()
