from pathlib import Path

import pytest

pytest.importorskip("torch", reason="torch is in the model extra and absent in CI")
pytest.importorskip("transformers", reason="transformers is in the model extra")

from gisting.agent.cli import load_model
from gisting.manifest.verify import ManifestMismatch
from gisting.model_server.config import ModelConfig
from gisting.model_server.transformers_backend import TransformersModel
from gisting.shopify.demo_apply import UsageError


def test_a_gist_artifact_that_fails_verification_stops_the_agent_with_a_usage_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(config: ModelConfig, gist_dir: Path | None = None) -> TransformersModel:
        message = f"gist artifact {gist_dir} does not match this runtime: rules_sha256"
        raise ManifestMismatch(message)

    monkeypatch.setattr(TransformersModel, "load", refuse)
    config = ModelConfig(tmp_path, "cpu", tmp_path / "gist")
    with pytest.raises(UsageError, match="does not match this runtime"):
        load_model(config, "gist")


def test_full_mode_never_asks_the_loader_for_a_gist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[Path | None] = []

    def refuse(config: ModelConfig, gist_dir: Path | None = None) -> TransformersModel:
        seen.append(gist_dir)
        message = "stop here"
        raise OSError(message)

    monkeypatch.setattr(TransformersModel, "load", refuse)
    with pytest.raises(UsageError):
        load_model(ModelConfig(tmp_path, "cpu", tmp_path / "gist"), "full")
    assert seen == [None]
