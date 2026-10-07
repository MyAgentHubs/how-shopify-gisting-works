import json
import os
from pathlib import Path

import pytest

from gisting.training.cli import USAGE_EXIT, main
from gisting.training.dataset import build_dataset
from gisting.training.errors import UsageError
from gisting.training.loading import apply_mps_watermark_defaults, load_runtime
from gisting.training.samples import sample_json


def test_build_writes_the_dataset_as_jsonl_on_stdout_and_nothing_on_stderr(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["build"]) == 0
    captured = capsys.readouterr()
    rows = [json.loads(line) for line in captured.out.splitlines()]
    assert rows == [json.loads(json.dumps(sample_json(s))) for s in build_dataset()]
    assert captured.err == ""


def test_build_can_write_a_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "nested" / "dataset.jsonl"
    assert main(["build", "--out", str(out)]) == 0
    assert capsys.readouterr().out == ""
    assert len(out.read_text().splitlines()) == len(build_dataset())


def test_teach_without_a_loadable_model_is_a_usage_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("GISTING_MODEL_DIR", str(tmp_path / "missing"))
    assert main(["teach", "--out", str(tmp_path / "t.jsonl")]) == USAGE_EXIT
    assert "cannot load the model" in capsys.readouterr().err


def test_an_unknown_command_is_rejected() -> None:
    with pytest.raises(SystemExit) as caught:
        main(["nope"])
    assert caught.value.code == USAGE_EXIT


MPS_WATERMARK_DEFAULTS = {
    "PYTORCH_MPS_HIGH_WATERMARK_RATIO": "0.7",
    "PYTORCH_MPS_LOW_WATERMARK_RATIO": "0.5",
}


def test_mps_watermark_defaults_fill_only_unset_variables() -> None:
    environ = {"PYTORCH_MPS_HIGH_WATERMARK_RATIO": "0.9"}
    apply_mps_watermark_defaults(environ)
    assert environ == {
        "PYTORCH_MPS_HIGH_WATERMARK_RATIO": "0.9",
        "PYTORCH_MPS_LOW_WATERMARK_RATIO": "0.5",
    }


def test_loading_a_runtime_sets_both_watermarks_before_the_model_loads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in MPS_WATERMARK_DEFAULTS:
        monkeypatch.setenv(name, "placeholder")
        monkeypatch.delenv(name)
    monkeypatch.setenv("GISTING_MODEL_DIR", str(tmp_path / "missing"))
    with pytest.raises(UsageError):
        load_runtime()
    assert {name: os.environ[name] for name in MPS_WATERMARK_DEFAULTS} == MPS_WATERMARK_DEFAULTS
