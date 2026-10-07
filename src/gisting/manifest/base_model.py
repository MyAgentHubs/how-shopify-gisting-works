from dataclasses import dataclass
from pathlib import Path

from gisting.manifest.record import ManifestError, sha256_file

REVISION_FILE = ".revision"
SUMS_FILE = "SHA256SUMS"


@dataclass(frozen=True)
class BaseModel:
    revision: str
    sha256: str


def read_base_model(model_dir: Path) -> BaseModel:
    revision_path, sums_path = model_dir / REVISION_FILE, model_dir / SUMS_FILE
    if not revision_path.is_file() or not sums_path.is_file():
        message = (
            f"{model_dir} lacks {REVISION_FILE} or {SUMS_FILE}; "
            "fetch it with scripts/download-models.sh"
        )
        raise ManifestError(message)
    revision = revision_path.read_text(encoding="utf-8").strip()
    if not revision:
        message = f"{revision_path} is empty"
        raise ManifestError(message)
    return BaseModel(revision, sha256_file(sums_path))
