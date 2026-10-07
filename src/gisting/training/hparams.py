import json
from dataclasses import dataclass
from pathlib import Path

from gisting.manifest.record import sha256_text
from gisting.shopify.jsonvalue import JsonObject, required_bool, required_int, required_str
from gisting.training.files import HPARAMS_FILE, read_object

INIT_CHOICES = ("chunk_mean", "random")


@dataclass(frozen=True)
class Hparams:
    k: int
    seed: int
    lr: float
    epochs: int
    batch_size: int
    max_len: int
    grad_clip: float
    init: str
    gradient_checkpointing: bool


def positive_float(document: JsonObject, key: str) -> float:
    value = document.get(key)
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
        message = f"hparams {key} must be a positive number"
        raise ValueError(message)
    return float(value)


def parse_hparams(document: JsonObject) -> Hparams:
    hparams = Hparams(
        k=required_int(document, "k"),
        seed=required_int(document, "seed"),
        lr=positive_float(document, "lr"),
        epochs=required_int(document, "epochs"),
        batch_size=required_int(document, "batch_size"),
        max_len=required_int(document, "max_len"),
        grad_clip=positive_float(document, "grad_clip"),
        init=required_str(document, "init"),
        gradient_checkpointing=required_bool(document, "gradient_checkpointing"),
    )
    if min(hparams.k, hparams.epochs, hparams.batch_size, hparams.max_len) < 1:
        message = "hparams k, epochs, batch_size and max_len must be at least 1"
        raise ValueError(message)
    if hparams.init not in INIT_CHOICES:
        message = f"hparams init must be one of {INIT_CHOICES}"
        raise ValueError(message)
    return hparams


def load_hparams(path: Path = HPARAMS_FILE) -> Hparams:
    return parse_hparams(read_object(path))


def hparams_sha256(path: Path = HPARAMS_FILE) -> str:
    return sha256_text(json.dumps(read_object(path), sort_keys=True))
