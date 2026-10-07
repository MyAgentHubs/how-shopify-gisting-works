from pathlib import Path

import torch
from safetensors.torch import load_file, save_file

from gisting.manifest.base_model import read_base_model
from gisting.manifest.record import GIST_FILE, GistManifest, ManifestError, read_manifest
from gisting.manifest.verify import Expected, verify_manifest
from gisting.model_server.gist import GistInjection, check_placeholder_fits
from gisting.prompt.fingerprint import rules_sha256, tools_sha256
from gisting.prompt.tokenizer import PromptTokenizer

TENSOR_NAME = "gist"


def write_gist(directory: Path, vectors: torch.Tensor) -> Path:
    path = directory / GIST_FILE
    save_file({TENSOR_NAME: vectors.detach().to("cpu", torch.float32).contiguous()}, str(path))
    return path


def read_gist(directory: Path) -> torch.Tensor:
    try:
        return load_file(str(directory / GIST_FILE))[TENSOR_NAME]
    except (OSError, KeyError, ValueError) as error:
        message = f"cannot read gist vectors from {directory}: {type(error).__name__}: {error}"
        raise ManifestError(message) from error


def expected_for(
    model_dir: Path, tokenizer: PromptTokenizer, hidden_size: int, backend_id: str
) -> Expected:
    base = read_base_model(model_dir)
    return Expected(
        base.revision,
        base.sha256,
        rules_sha256(),
        tools_sha256(tokenizer),
        hidden_size,
        tokenizer.gist_placeholder,
        backend_id,
    )


def check_shape(manifest: GistManifest, vectors: torch.Tensor) -> None:
    if vectors.dtype != torch.float32 or tuple(vectors.shape) != (manifest.k, manifest.hidden_size):
        message = (
            f"gist tensor is {vectors.dtype} {tuple(vectors.shape)}, "
            f"manifest says float32 {(manifest.k, manifest.hidden_size)}"
        )
        raise ManifestError(message)


def load_gist(
    directory: Path, expected: Expected, embedding: torch.nn.Embedding
) -> tuple[GistInjection, GistManifest]:
    manifest = read_manifest(directory)
    verify_manifest(directory, manifest, expected)
    vectors = read_gist(directory)
    check_shape(manifest, vectors)
    check_placeholder_fits(embedding, expected.placeholder_id)
    return GistInjection(vectors, expected.placeholder_id), manifest
