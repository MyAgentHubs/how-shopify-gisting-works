import os
from pathlib import Path

import pytest

DEFAULT_MODEL_DIR = Path("~/models/hf/qwen3-1.7b")
MODEL_DIR = Path(os.environ.get("GISTING_MODEL_DIR") or DEFAULT_MODEL_DIR).expanduser()
HAS_TOKENIZER = (MODEL_DIR / "tokenizer.json").is_file()
HAS_WEIGHTS = HAS_TOKENIZER and (MODEL_DIR / "config.json").is_file()

needs_tokenizer = pytest.mark.skipif(
    not HAS_TOKENIZER,
    reason=f"no tokenizer.json in {MODEL_DIR}; CI has no model files, run locally with them",
)
