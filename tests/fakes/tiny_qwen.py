from pathlib import Path

import pytest
from fakes.tokenizer import synthetic_prompt_tokenizer

torch = pytest.importorskip("torch", reason="torch is in the model extra and absent in CI")
transformers = pytest.importorskip("transformers", reason="transformers is in the model extra")

from gisting.model_server.gist import GistInjection  # noqa: E402
from gisting.model_server.transformers_backend import TransformersModel  # noqa: E402
from gisting.prompt.tokenizer import PromptTokenizer  # noqa: E402

HIDDEN = 32
K = 4


def tiny_model(gist: GistInjection | None = None, seed: int = 0) -> TransformersModel:
    torch.manual_seed(seed)
    config = transformers.Qwen3Config(
        vocab_size=700,
        hidden_size=HIDDEN,
        intermediate_size=64,
        num_hidden_layers=2,
        num_attention_heads=4,
        num_key_value_heads=2,
        head_dim=8,
        max_position_embeddings=8192,
        tie_word_embeddings=True,
    )
    network = transformers.Qwen3ForCausalLM(config).eval()
    return TransformersModel(network, synthetic_prompt_tokenizer(), "cpu", torch.float32, gist)


def random_gist(tokenizer: PromptTokenizer, seed: int = 1) -> GistInjection:
    generator = torch.Generator().manual_seed(seed)
    vectors = torch.randn(K, HIDDEN, generator=generator)
    return GistInjection(vectors, tokenizer.gist_placeholder)


def make_model_dir(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / ".revision").write_text("rev-test\n")
    (directory / "SHA256SUMS").write_text("0" * 64 + "  model.safetensors\n")
    return directory
