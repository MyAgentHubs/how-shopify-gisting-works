from pathlib import Path

import pytest
from fakes.tiny_qwen import K, make_model_dir, random_gist, tiny_model
from fakes.tokenizer import synthetic_prompt_tokenizer
from loading_support import CANARY, MANIFEST, serve_env

from gisting.model_server.config import ModelConfig
from gisting.model_server.transformers_backend import TransformersModel
from gisting.prompt.tokenizer import PromptTokenizer
from gisting.serve.config import ServeEnv
from gisting.serve.loading import LoadError, load_models, transformers_loader

TOKENIZER = synthetic_prompt_tokenizer()


def env_with_model_dir(tmp_path: Path) -> ServeEnv:
    return ServeEnv(8123, "u" * 32, "e", "s", make_model_dir(tmp_path / "model"), tmp_path)


def test_both_modes_share_one_copy_of_the_weights(tmp_path: Path) -> None:
    model = tiny_model(random_gist(TOKENIZER))
    model.gist_manifest = MANIFEST
    env = env_with_model_dir(tmp_path)
    gist, full = load_models(env, lambda _config: (model, TOKENIZER))
    assert isinstance(gist.model, TransformersModel)
    assert isinstance(full.model, TransformersModel)
    assert gist.model.gist is not None
    assert full.model.gist is None
    assert full.model.network is gist.model.network
    assert gist.gist_count == K
    assert "gist" in gist.identity
    assert "gist" not in full.identity
    assert full.identity["base_model_revision"] == "rev-test"
    assert full.identity["base_model_sha256"] == gist.identity["base_model_sha256"]


def test_the_default_loader_asks_the_backend_once_for_the_gist_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked: list[tuple[ModelConfig, Path | None]] = []

    def load(config: ModelConfig, gist_dir: Path | None = None) -> TransformersModel:
        asked.append((config, gist_dir))
        message = f"{CANARY} {config.model_dir}"
        raise RuntimeError(message)

    monkeypatch.setattr(TransformersModel, "load", staticmethod(load))
    env = serve_env(tmp_path)
    with pytest.raises(LoadError) as caught:
        load_models(env, transformers_loader)
    assert len(asked) == 1
    assert asked[0][1] == env.gist_dir
    assert "RuntimeError" in str(caught.value)
    assert CANARY not in str(caught.value)
    assert str(tmp_path) not in str(caught.value)


def test_the_default_loader_returns_the_loaded_model_with_the_tokenizer_of_its_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = tiny_model(random_gist(TOKENIZER))
    monkeypatch.setattr(TransformersModel, "load", staticmethod(lambda *_args: model))

    def from_dir(_path: Path) -> PromptTokenizer:
        return TOKENIZER

    monkeypatch.setattr(PromptTokenizer, "from_dir", staticmethod(from_dir))
    config = ModelConfig(tmp_path, None, tmp_path)
    loaded, tokenizer = transformers_loader(config)
    assert loaded is model
    assert tokenizer is TOKENIZER
