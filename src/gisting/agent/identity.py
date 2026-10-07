from pathlib import Path

from gisting.manifest.base_model import read_base_model
from gisting.manifest.record import GistManifest, ManifestError
from gisting.shopify.jsonvalue import JsonObject


def model_identity(model_dir: Path, gist: GistManifest | None) -> JsonObject:
    identity: JsonObject = {}
    try:
        base = read_base_model(model_dir)
        identity = {"base_model_revision": base.revision, "base_model_sha256": base.sha256}
    except ManifestError:
        identity = {}
    if gist is not None:
        identity["gist"] = {
            "run_id": gist.run_id,
            "k": gist.k,
            "gist_sha256": gist.gist_sha256,
            "dataset_sha256": gist.dataset_sha256,
            "train_config_sha256": gist.train_config_sha256,
            "rules_sha256": gist.rules_sha256,
            "tools_sha256": gist.tools_sha256,
        }
    return identity
