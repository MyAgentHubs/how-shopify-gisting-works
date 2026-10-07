import json
from pathlib import Path

import pytest

from gisting.shopify.jsonvalue import Json, JsonObject
from gisting.training.hparams import hparams_sha256, load_hparams, parse_hparams

GOOD: JsonObject = {
    "k": 16,
    "seed": 1,
    "lr": 0.01,
    "epochs": 2,
    "batch_size": 4,
    "max_len": 512,
    "grad_clip": 1.0,
    "init": "chunk_mean",
    "gradient_checkpointing": False,
}


def test_the_shipped_hparams_are_valid_and_default_to_sixteen_vectors() -> None:
    hparams = load_hparams()
    assert hparams.k == 16
    assert hparams.init in ("chunk_mean", "random")


def test_hparams_fingerprint_is_stable_hex() -> None:
    assert hparams_sha256() == hparams_sha256()
    assert len(hparams_sha256()) == 64


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("k", 0),
        ("epochs", 0),
        ("batch_size", 0),
        ("max_len", 0),
        ("lr", 0),
        ("lr", "x"),
        ("init", "zeros"),
    ],
)
def test_invalid_values_are_rejected(key: str, value: Json) -> None:
    with pytest.raises((ValueError, TypeError)):
        parse_hparams({**GOOD, key: value})


def test_missing_keys_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "h.json"
    path.write_text(json.dumps({"k": 4}))
    with pytest.raises(ValueError):
        load_hparams(path)
