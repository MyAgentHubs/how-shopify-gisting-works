from dataclasses import dataclass
from pathlib import Path

from fakes.tokenizer import synthetic_prompt_tokenizer

from gisting.manifest.record import GistManifest
from gisting.model_server.config import ModelConfig
from gisting.model_server.interface import Generation
from gisting.prompt.tokenizer import PromptTokenizer
from gisting.serve.config import ServeEnv
from gisting.serve.loading import LoadedModel, ModelLoader

CANARY = "CANARY-7731-secret"
GIST_COUNT = 16
MANIFEST = GistManifest(
    "run-1",
    "rev1",
    "b" * 64,
    "c" * 64,
    "d" * 64,
    GIST_COUNT,
    32,
    700,
    "e" * 64,
    "f" * 64,
    "cpu",
    "a" * 64,
)


def environ_in(tmp_path: Path) -> dict[str, str]:
    model_dir = tmp_path / f"{CANARY}-model"
    gist_dir = tmp_path / f"{CANARY}-gist"
    model_dir.mkdir()
    gist_dir.mkdir()
    return {
        "GISTING_SERVE_PORT": "8123",
        "GISTING_UPSTREAM_SECRET": f"{CANARY}-upstream-" + "x" * 32,
        "GISTING_EMAIL_SECRET": f"{CANARY}-email-" + "y" * 32,
        "SHOPIFY_CLIENT_SECRET": f"{CANARY}-shopify",
        "GISTING_MODEL_DIR": str(model_dir),
        "GISTING_GIST_DIR": str(gist_dir),
    }


def serve_env(tmp_path: Path) -> ServeEnv:
    model_dir = tmp_path / "model"
    model_dir.mkdir(exist_ok=True)
    return ServeEnv(8123, "u" * 32, "email-secret", "shopify-secret", model_dir, tmp_path)


@dataclass(frozen=True)
class StubGist:
    count: int = GIST_COUNT


@dataclass
class StubModel:
    backend_id: str = "stub"
    gist: "StubGist | None" = None
    gist_manifest: GistManifest | None = None

    def generate(self, ids: list[int], max_new_tokens: int) -> Generation:
        raise AssertionError((ids, max_new_tokens))

    def count(self, text: str) -> int:
        return len(text)

    def without_gist(self) -> "StubModel":
        return StubModel(self.backend_id)


def stub_loader(model: LoadedModel) -> ModelLoader:
    def load(config: ModelConfig) -> tuple[LoadedModel, PromptTokenizer]:
        assert config.gist_dir is not None
        return model, synthetic_prompt_tokenizer()

    return load
