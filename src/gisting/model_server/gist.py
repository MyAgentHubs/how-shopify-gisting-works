import hashlib
from collections.abc import Callable
from dataclasses import dataclass

import torch


class GistInjectionError(ValueError):
    pass


@dataclass(frozen=True)
class GistInjection:
    vectors: torch.Tensor
    placeholder_id: int

    @property
    def count(self) -> int:
        return int(self.vectors.shape[0])


def check_placeholder_fits(embedding: torch.nn.Embedding, placeholder_id: int) -> None:
    rows = int(embedding.num_embeddings)
    if placeholder_id >= rows:
        message = f"placeholder id {placeholder_id} is outside the {rows} embedding rows"
        raise GistInjectionError(message)


def embed_with_gist(
    embedding: Callable[[torch.Tensor], torch.Tensor],
    ids: torch.Tensor,
    placeholder_id: int,
    gist: GistInjection | None,
) -> torch.Tensor:
    if ids.shape[0] != 1:
        message = "gist injection supports one sequence at a time"
        raise GistInjectionError(message)
    positions = (ids[0] == placeholder_id).nonzero().squeeze(-1)
    expected = 0 if gist is None else gist.count
    if positions.numel() != expected:
        message = (
            f"prompt has {positions.numel()} gist placeholders but {expected} vectors are loaded"
        )
        raise GistInjectionError(message)
    embeds = embedding(ids)
    if gist is None:
        return embeds
    return embeds.index_copy(1, positions, gist.vectors.to(embeds.dtype)[None])


def parameters_sha256(network: torch.nn.Module) -> str:
    digest = hashlib.sha256()
    for name, tensor in sorted(network.state_dict().items()):
        digest.update(name.encode())
        digest.update(str(tuple(tensor.shape)).encode())
        flat = tensor.detach().cpu().contiguous().reshape(-1).view(torch.uint8)
        digest.update(memoryview(flat.numpy()).cast("B"))
    return digest.hexdigest()
