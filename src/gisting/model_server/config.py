from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

DEFAULT_MODEL_DIR = "~/models/hf/qwen3-1.7b"


@dataclass(frozen=True)
class ModelConfig:
    model_dir: Path
    device: str | None
    gist_dir: Path | None = None


def load_config(environ: Mapping[str, str]) -> ModelConfig:
    model_dir = environ.get("GISTING_MODEL_DIR") or DEFAULT_MODEL_DIR
    gist_dir = environ.get("GISTING_GIST_DIR")
    return ModelConfig(
        Path(model_dir).expanduser(),
        environ.get("GISTING_DEVICE") or None,
        Path(gist_dir).expanduser() if gist_dir else None,
    )
