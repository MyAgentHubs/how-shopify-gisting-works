import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"

Populate = Callable[[dict[str, str]], Path]
Guard = Callable[..., "subprocess.CompletedProcess[str]"]


@pytest.fixture
def populate(tmp_path: Path) -> Populate:
    def write(files: dict[str, str]) -> Path:
        for relative, text in files.items():
            target = tmp_path / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        return tmp_path

    return write


@pytest.fixture
def guard() -> Guard:
    def run(script: str, root: Path, *extra: str) -> "subprocess.CompletedProcess[str]":
        command = [sys.executable, str(SCRIPTS_DIR / script), "--root", str(root), *extra]
        return subprocess.run(command, capture_output=True, text=True, check=False)

    return run
