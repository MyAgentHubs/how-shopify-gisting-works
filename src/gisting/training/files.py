import json
from pathlib import Path

from gisting.shopify.jsonvalue import Json, JsonObject

ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = ROOT / "data" / "gist"
PLAN_FILE = ROOT / "data" / "demo-orders" / "shipment-plan-v1.json"
TEMPLATES_FILE = DATA_DIR / "templates.json"
HPARAMS_FILE = DATA_DIR / "hparams.json"
DEFAULT_ARTIFACTS = ROOT / "artifacts" / "gist"


class DataFileError(ValueError):
    pass


def read_object(path: Path) -> JsonObject:
    try:
        loaded: Json = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        message = f"cannot read {path}: {type(error).__name__}: {error}"
        raise DataFileError(message) from error
    if not isinstance(loaded, dict):
        message = f"{path} must hold a JSON object"
        raise DataFileError(message)
    return loaded
