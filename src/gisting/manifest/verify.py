from dataclasses import dataclass, fields
from pathlib import Path

from gisting.manifest.record import GIST_FILE, GistManifest, ManifestError, sha256_file


class ManifestMismatch(ManifestError):
    pass


@dataclass(frozen=True)
class Expected:
    base_model_revision: str
    base_model_sha256: str
    rules_sha256: str
    tools_sha256: str
    hidden_size: int
    placeholder_id: int
    backend_id: str


def differences(manifest: GistManifest, expected: Expected) -> list[str]:
    found: list[str] = []
    for field in fields(Expected):
        want, have = getattr(expected, field.name), getattr(manifest, field.name)
        if want != have:
            found.append(f"{field.name}: artifact has {have}, runtime has {want}")
    return found


def verify_manifest(directory: Path, manifest: GistManifest, expected: Expected) -> None:
    path = directory / GIST_FILE
    if not path.is_file():
        message = f"gist artifact {path} is missing"
        raise ManifestMismatch(message)
    found = differences(manifest, expected)
    actual = sha256_file(path)
    if actual != manifest.gist_sha256:
        found.append(f"gist_sha256: manifest has {manifest.gist_sha256}, file has {actual}")
    if found:
        message = f"gist artifact {directory} does not match this runtime: " + "; ".join(found)
        raise ManifestMismatch(message)
