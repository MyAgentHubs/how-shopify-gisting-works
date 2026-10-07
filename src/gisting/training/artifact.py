from dataclasses import dataclass
from pathlib import Path

import torch

from gisting.manifest.base_model import read_base_model
from gisting.manifest.record import GistManifest, sha256_file, write_manifest
from gisting.model_server.gist_store import write_gist
from gisting.prompt.fingerprint import rules_sha256, tools_sha256
from gisting.prompt.tokenizer import PromptTokenizer


@dataclass(frozen=True)
class Provenance:
    run_id: str
    model_dir: Path
    backend_id: str
    train_config_sha256: str
    dataset_sha256: str


def write_artifact(
    directory: Path, vectors: torch.Tensor, tokenizer: PromptTokenizer, origin: Provenance
) -> GistManifest:
    directory.mkdir(parents=True, exist_ok=True)
    path = write_gist(directory, vectors)
    base = read_base_model(origin.model_dir)
    manifest = GistManifest(
        run_id=origin.run_id,
        base_model_revision=base.revision,
        base_model_sha256=base.sha256,
        rules_sha256=rules_sha256(),
        tools_sha256=tools_sha256(tokenizer),
        k=int(vectors.shape[0]),
        hidden_size=int(vectors.shape[1]),
        placeholder_id=tokenizer.gist_placeholder,
        train_config_sha256=origin.train_config_sha256,
        dataset_sha256=origin.dataset_sha256,
        backend_id=origin.backend_id,
        gist_sha256=sha256_file(path),
    )
    write_manifest(directory, manifest)
    return manifest
