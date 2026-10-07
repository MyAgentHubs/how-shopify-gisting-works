import copy
import time
from pathlib import Path
from typing import Any

import torch
from transformers import AutoModelForCausalLM

from gisting.manifest.record import GistManifest
from gisting.model_server.config import ModelConfig
from gisting.model_server.gist import GistInjection, embed_with_gist
from gisting.model_server.gist_store import expected_for, load_gist
from gisting.model_server.interface import Generation
from gisting.prompt import tokenizer as tok
from gisting.prompt.tokenizer import PromptTokenizer

STOP_TOKENS = (tok.IM_END, "<|endoftext|>")
MPS_DTYPE = torch.bfloat16
CPU_DTYPE = torch.float32
MS_PER_SECOND = 1000.0


def default_device() -> str:
    return "mps" if torch.backends.mps.is_available() else "cpu"


def backend_name(device: str, dtype: torch.dtype) -> str:
    return f"transformers-{device}-{str(dtype).removeprefix('torch.')}"


class TransformersModel:
    def __init__(
        self,
        model: torch.nn.Module,
        tokenizer: PromptTokenizer,
        device: str,
        dtype: torch.dtype,
        gist: GistInjection | None = None,
    ) -> None:
        self.network: Any = model
        self.gist = gist
        self.gist_manifest: GistManifest | None = None
        self._tokenizer = tokenizer
        self._device = device
        self.stop_ids = frozenset(tokenizer.control(token) for token in STOP_TOKENS)
        self.backend_id = backend_name(device, dtype)

    @classmethod
    def load(cls, config: ModelConfig, gist_dir: Path | None = None) -> "TransformersModel":
        device = config.device or default_device()
        dtype = MPS_DTYPE if device == "mps" else CPU_DTYPE
        loader: Any = AutoModelForCausalLM
        model = loader.from_pretrained(str(config.model_dir), dtype=dtype, local_files_only=True)
        model.to(device).eval()
        tokenizer = PromptTokenizer.from_dir(config.model_dir)
        loaded = cls(model, tokenizer, device, dtype)
        if gist_dir is not None:
            loaded.attach_gist(gist_dir, config.model_dir)
        return loaded

    def attach_gist(self, gist_dir: Path, model_dir: Path) -> None:
        hidden_size = int(self.network.config.hidden_size)
        expected = expected_for(model_dir, self._tokenizer, hidden_size, self.backend_id)
        injection, manifest = load_gist(gist_dir, expected, self.network.get_input_embeddings())
        self.gist = GistInjection(injection.vectors.to(self._device), injection.placeholder_id)
        self.gist_manifest = manifest

    def without_gist(self) -> "TransformersModel":
        view = copy.copy(self)
        view.gist = None
        view.gist_manifest = None
        return view

    def prefill_embeds(self, ids: list[int]) -> torch.Tensor:
        tensor = torch.tensor([ids], device=self._device)
        embedding = self.network.get_input_embeddings()
        return embed_with_gist(embedding, tensor, self._tokenizer.gist_placeholder, self.gist)

    def count(self, text: str) -> int:
        return len(self._tokenizer.encode_text(text))

    def generate(self, ids: list[int], max_new_tokens: int) -> Generation:
        started = time.perf_counter()
        first_token_ms = 0.0
        generated: list[int] = []
        finish_reason = "length"
        cache = None
        with torch.inference_mode():
            step: dict[str, torch.Tensor] = {"inputs_embeds": self.prefill_embeds(ids)}
            for index in range(max_new_tokens):
                output = self.network(**step, past_key_values=cache, use_cache=True)
                cache = output.past_key_values
                next_id = int(output.logits[0, -1].argmax())
                if index == 0:
                    first_token_ms = (time.perf_counter() - started) * MS_PER_SECOND
                if next_id in self.stop_ids:
                    finish_reason = "stop"
                    break
                generated.append(next_id)
                step = {"input_ids": torch.tensor([[next_id]], device=self._device)}
        total_ms = (time.perf_counter() - started) * MS_PER_SECOND
        text = self._tokenizer.decode(generated)
        return Generation(text, tuple(generated), first_token_ms, total_ms, finish_reason)
