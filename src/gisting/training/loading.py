import os
from collections.abc import MutableMapping
from pathlib import Path
from typing import TYPE_CHECKING

from gisting.model_server.config import ModelConfig, load_config
from gisting.prompt.tokenizer import PromptTokenizer, TokenizerUnavailable
from gisting.training.errors import UsageError

if TYPE_CHECKING:
    from gisting.model_server.transformers_backend import TransformersModel


def apply_mps_watermark_defaults(environ: MutableMapping[str, str]) -> None:
    environ.setdefault("PYTORCH_MPS_HIGH_WATERMARK_RATIO", "0.7")
    environ.setdefault("PYTORCH_MPS_LOW_WATERMARK_RATIO", "0.5")


def load_runtime(
    gist_dir: Path | None = None,
) -> tuple[ModelConfig, "TransformersModel", PromptTokenizer]:
    apply_mps_watermark_defaults(os.environ)
    config = load_config(os.environ)
    try:
        from gisting.model_server.transformers_backend import TransformersModel

        model = TransformersModel.load(config, gist_dir)
        tokenizer = PromptTokenizer.from_dir(config.model_dir)
    except (ImportError, OSError, TokenizerUnavailable) as error:
        message = f"cannot load the model from {config.model_dir}: {type(error).__name__}: {error}"
        raise UsageError(message) from error
    return config, model, tokenizer
