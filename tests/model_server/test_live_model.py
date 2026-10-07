import pytest
from fakes.real_model import HAS_WEIGHTS, MODEL_DIR

from gisting.model_server.config import ModelConfig, load_config


@pytest.mark.live
@pytest.mark.skipif(not HAS_WEIGHTS, reason=f"no model weights in {MODEL_DIR}")
def test_real_model_greedy_answers_a_trivial_prompt() -> None:
    from gisting.model_server.transformers_backend import TransformersModel
    from gisting.prompt.tokenizer import PromptTokenizer

    model = TransformersModel.load(ModelConfig(MODEL_DIR, load_config({}).device))
    tokenizer = PromptTokenizer.from_dir(MODEL_DIR)
    prompt = tokenizer.encode_trusted(
        "<|im_start|>user\nReply with the single word OK.<|im_end|>\n"
        "<|im_start|>assistant\n<think>\n\n</think>\n\n"
    )
    first = model.generate(prompt, 16)
    again = model.generate(prompt, 16)
    assert "OK" in first.text
    assert first.finish_reason == "stop"
    assert first.ids == again.ids
    assert 0 < first.first_token_ms <= first.total_ms
