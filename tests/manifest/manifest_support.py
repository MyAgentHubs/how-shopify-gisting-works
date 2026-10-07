from dataclasses import replace
from pathlib import Path

from gisting.manifest.record import GIST_FILE, GistManifest, sha256_file, write_manifest
from gisting.manifest.verify import Expected

HEX = "a" * 64


def manifest(**changes: str | int) -> GistManifest:
    base = GistManifest(
        run_id="run-1",
        base_model_revision="rev1",
        base_model_sha256="b" * 64,
        rules_sha256="c" * 64,
        tools_sha256="d" * 64,
        k=16,
        hidden_size=32,
        placeholder_id=700,
        train_config_sha256="e" * 64,
        dataset_sha256="f" * 64,
        backend_id="transformers-cpu-float32",
        gist_sha256=HEX,
    )
    return replace(base, **changes)


def expected_of(item: GistManifest) -> Expected:
    return Expected(
        item.base_model_revision,
        item.base_model_sha256,
        item.rules_sha256,
        item.tools_sha256,
        item.hidden_size,
        item.placeholder_id,
        item.backend_id,
    )


def artifact(directory: Path, payload: bytes = b"gist-bytes") -> GistManifest:
    (directory / GIST_FILE).write_bytes(payload)
    item = manifest(gist_sha256=sha256_file(directory / GIST_FILE))
    write_manifest(directory, item)
    return item
