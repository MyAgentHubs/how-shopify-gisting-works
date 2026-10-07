import pytest
from fakes.tokenizer import synthetic_prompt_tokenizer

torch = pytest.importorskip("torch", reason="torch is in the model extra and absent in CI")
transformers = pytest.importorskip("transformers", reason="transformers is in the model extra")

from gisting.model_server.transformers_backend import TransformersModel  # noqa: E402
from gisting.prompt.tokenizer import IM_END  # noqa: E402

PROMPT_IDS = [5, 40, 77, 120, 9, 33]


def tiny_model() -> TransformersModel:
    torch.manual_seed(0)
    config = transformers.Qwen3Config(
        vocab_size=700,
        hidden_size=32,
        intermediate_size=64,
        num_hidden_layers=2,
        num_attention_heads=4,
        num_key_value_heads=2,
        head_dim=8,
        max_position_embeddings=256,
    )
    network = transformers.Qwen3ForCausalLM(config).eval()
    return TransformersModel(network, synthetic_prompt_tokenizer(), "cpu", torch.float32)


def reference_ids(model: TransformersModel, count: int) -> list[int]:
    network = model.network
    out = network.generate(
        torch.tensor([PROMPT_IDS]), max_new_tokens=count, do_sample=False, min_new_tokens=count
    )
    return [int(token) for token in out[0, len(PROMPT_IDS) :]]


def test_greedy_ids_match_transformers_generate() -> None:
    model = tiny_model()
    model.stop_ids = frozenset()
    result = model.generate(PROMPT_IDS, 12)
    assert list(result.ids) == reference_ids(model, 12)
    assert result.finish_reason == "length"


def test_stops_on_a_stop_token_and_does_not_return_it() -> None:
    model = tiny_model()
    model.stop_ids = frozenset()
    free = model.generate(PROMPT_IDS, 6)
    model.stop_ids = frozenset({free.ids[3]})
    stopped = model.generate(PROMPT_IDS, 6)
    assert stopped.ids == free.ids[:3]
    assert stopped.finish_reason == "stop"


def test_timings_are_ordered_and_text_is_decoded() -> None:
    model = tiny_model()
    result = model.generate(PROMPT_IDS, 4)
    assert 0 < result.first_token_ms <= result.total_ms
    assert result.text == synthetic_prompt_tokenizer().decode(list(result.ids))


def test_default_stop_tokens_include_im_end() -> None:
    tokenizer = synthetic_prompt_tokenizer()
    assert tokenizer.control(IM_END) in tiny_model().stop_ids


def test_count_uses_the_prompt_tokenizer() -> None:
    model = tiny_model()
    assert model.count("order #1042") == len(
        synthetic_prompt_tokenizer().encode_text("order #1042")
    )
    assert model.backend_id == "transformers-cpu-float32"
