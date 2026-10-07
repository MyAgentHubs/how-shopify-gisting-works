import random
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

import torch
from transformers import PreTrainedModel

from gisting.model_server.gist import GistInjection
from gisting.shopify.jsonvalue import JsonObject
from gisting.training.examples import Example
from gisting.training.forward import kl_per_token, student_logits, teacher_logits
from gisting.training.hparams import Hparams

LogRow = JsonObject


@dataclass
class Run:
    network: PreTrainedModel
    placeholder_id: int
    hparams: Hparams
    gist: torch.nn.Parameter
    log: list[LogRow] = field(default_factory=lambda: [])


@contextmanager
def checkpointed(run: Run) -> Iterator[None]:
    network = run.network
    if run.hparams.gradient_checkpointing:
        network.gradient_checkpointing_enable(
            gradient_checkpointing_kwargs={"use_reentrant": False}
        )
        network.train()
    try:
        yield
    finally:
        network.gradient_checkpointing_disable()
        network.eval()


def release_device_cache() -> None:
    if torch.backends.mps.is_available():
        torch.mps.empty_cache()


def example_kl(run: Run, example: Example) -> torch.Tensor:
    teacher = teacher_logits(run.network, example.teacher_ids, example.teacher_positions)
    injection = GistInjection(run.gist, run.placeholder_id)
    student = student_logits(run.network, example.student_ids, example.student_positions, injection)
    return kl_per_token(teacher, student).mean()


def dev_kl(run: Run, examples: list[Example]) -> float:
    with torch.no_grad():
        values: list[float] = []
        for example in examples:
            values.append(float(example_kl(run, example)))
            release_device_cache()
    return sum(values) / len(values)


def train_batch(
    run: Run, batch: list[Example], optimizer: torch.optim.Optimizer
) -> tuple[float, float]:
    optimizer.zero_grad()
    total = 0.0
    for example in batch:
        loss = example_kl(run, example)
        if not torch.isfinite(loss):
            message = f"non-finite loss on {example.sample_id}"
            raise FloatingPointError(message)
        (loss / len(batch)).backward()
        total += float(loss.detach())
        del loss
        release_device_cache()
    norm = torch.nn.utils.clip_grad_norm_([run.gist], run.hparams.grad_clip)
    optimizer.step()
    return total / len(batch), float(norm)


def log_row(run: Run, row: LogRow) -> None:
    run.log.append(row)
    sys.stderr.write(f"gisting.training: {row}\n")


def train(
    run: Run,
    train_set: list[Example],
    dev_set: list[Example],
    on_epoch: Callable[[Run], None] = lambda _run: None,
) -> None:
    with checkpointed(run):
        fit(run, train_set, dev_set, on_epoch)


def fit(
    run: Run, train_set: list[Example], dev_set: list[Example], on_epoch: Callable[[Run], None]
) -> None:
    hp = run.hparams
    optimizer = torch.optim.AdamW([run.gist], lr=hp.lr, weight_decay=0.0)
    log_row(run, {"event": "dev", "epoch": 0, "dev_kl": dev_kl(run, dev_set)})
    step = 0
    for epoch in range(1, hp.epochs + 1):
        order = list(train_set)
        random.Random(hp.seed + epoch).shuffle(order)
        for start in range(0, len(order), hp.batch_size):
            step += 1
            loss, norm = train_batch(run, order[start : start + hp.batch_size], optimizer)
            log_row(
                run,
                {"event": "step", "epoch": epoch, "step": step, "loss": loss, "grad_norm": norm},
            )
        log_row(run, {"event": "dev", "epoch": epoch, "dev_kl": dev_kl(run, dev_set)})
        on_epoch(run)
