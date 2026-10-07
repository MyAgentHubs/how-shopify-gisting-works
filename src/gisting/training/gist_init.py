from typing import cast

import torch
from transformers import PreTrainedModel

from gisting.training.kit import Kit

SEED_OFFSET = 1


def input_embedding(network: PreTrainedModel) -> torch.nn.Embedding:
    return cast(torch.nn.Embedding, network.get_input_embeddings())


def chunk_mean_init(network: PreTrainedModel, kit: Kit, count: int) -> torch.Tensor:
    embedding = input_embedding(network)
    ids = torch.tensor(kit.full.ids, device=embedding.weight.device)
    with torch.no_grad():
        embeds = embedding(ids).float()
        return torch.stack([chunk.mean(0) for chunk in torch.tensor_split(embeds, count)])


def random_init(network: PreTrainedModel, count: int, seed: int) -> torch.Tensor:
    weight = input_embedding(network).weight
    generator = torch.Generator().manual_seed(seed + SEED_OFFSET)
    scale = float(weight.detach().float().std())
    return (torch.randn(count, weight.shape[1], generator=generator) * scale).to(weight.device)


def initial_gist(
    network: PreTrainedModel, kit: Kit, init: str, seed: int, count: int
) -> torch.Tensor:
    if init == "chunk_mean":
        return chunk_mean_init(network, kit, count)
    return random_init(network, count, seed)
