import json
import os
from pathlib import Path

from gisting.shopify.jsonvalue import JsonObject


class Ledger:
    def __init__(self, path: Path) -> None:
        self._path = path

    def record(self, entry: JsonObject) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(entry, sort_keys=True, ensure_ascii=False)
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
            handle.flush()
            os.fsync(handle.fileno())
