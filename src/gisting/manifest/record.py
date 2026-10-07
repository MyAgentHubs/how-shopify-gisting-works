import hashlib
import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import cast

SCHEMA_VERSION = 1
MANIFEST_FILE = "manifest.json"
GIST_FILE = "gist.safetensors"
READ_CHUNK = 1 << 20


class ManifestError(ValueError):
    pass


@dataclass(frozen=True)
class GistManifest:
    run_id: str
    base_model_revision: str
    base_model_sha256: str
    rules_sha256: str
    tools_sha256: str
    k: int
    hidden_size: int
    placeholder_id: int
    train_config_sha256: str
    dataset_sha256: str
    backend_id: str
    gist_sha256: str


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(READ_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def dump_manifest(manifest: GistManifest) -> str:
    document = {"schema": SCHEMA_VERSION, **asdict(manifest)}
    return json.dumps(document, indent=2, sort_keys=True) + "\n"


def parse_manifest(text: str) -> GistManifest:
    try:
        loaded: object = json.loads(text)
    except ValueError as error:
        message = f"manifest is not valid JSON: {error}"
        raise ManifestError(message) from error
    if not isinstance(loaded, dict):
        message = "manifest must be a JSON object"
        raise ManifestError(message)
    document = cast(dict[str, object], loaded)
    known = {field.name for field in fields(GistManifest)} | {"schema"}
    if document.get("schema") != SCHEMA_VERSION or set(document) != known:
        message = (
            f"manifest fields differ from schema {SCHEMA_VERSION}: {sorted(set(document) ^ known)}"
        )
        raise ManifestError(message)
    return GistManifest(
        run_id=text_at(document, "run_id"),
        base_model_revision=text_at(document, "base_model_revision"),
        base_model_sha256=text_at(document, "base_model_sha256"),
        rules_sha256=text_at(document, "rules_sha256"),
        tools_sha256=text_at(document, "tools_sha256"),
        k=count_at(document, "k"),
        hidden_size=count_at(document, "hidden_size"),
        placeholder_id=count_at(document, "placeholder_id"),
        train_config_sha256=text_at(document, "train_config_sha256"),
        dataset_sha256=text_at(document, "dataset_sha256"),
        backend_id=text_at(document, "backend_id"),
        gist_sha256=text_at(document, "gist_sha256"),
    )


def text_at(document: dict[str, object], name: str) -> str:
    value = document[name]
    if not isinstance(value, str) or not value:
        message = f"manifest field {name} must be a non-empty string"
        raise ManifestError(message)
    return value


def count_at(document: dict[str, object], name: str) -> int:
    value = document[name]
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        message = f"manifest field {name} must be a positive integer"
        raise ManifestError(message)
    return value


def write_manifest(directory: Path, manifest: GistManifest) -> Path:
    path = directory / MANIFEST_FILE
    path.write_text(dump_manifest(manifest), encoding="utf-8")
    return path


def read_manifest(directory: Path) -> GistManifest:
    try:
        return parse_manifest((directory / MANIFEST_FILE).read_text(encoding="utf-8"))
    except OSError as error:
        message = f"cannot read {directory / MANIFEST_FILE}: {error}"
        raise ManifestError(message) from error
