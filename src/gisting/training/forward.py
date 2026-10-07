import torch
import torch.nn.functional as functional
from transformers import PreTrainedModel

from gisting.model_server.gist import GistInjection, embed_with_gist


def logits_at(
    network: PreTrainedModel, embeds_or_ids: torch.Tensor, positions: torch.Tensor
) -> torch.Tensor:
    keep = {"logits_to_keep": positions, "use_cache": False}
    if embeds_or_ids.dtype.is_floating_point:
        return network(inputs_embeds=embeds_or_ids, **keep).logits[0].float()
    return network(input_ids=embeds_or_ids, **keep).logits[0].float()


def student_logits(
    network: PreTrainedModel,
    ids: torch.Tensor,
    positions: torch.Tensor,
    gist: GistInjection,
) -> torch.Tensor:
    embedding = network.get_input_embeddings()
    embeds = embed_with_gist(embedding, ids, gist.placeholder_id, gist)
    return logits_at(network, embeds, positions)


def teacher_logits(
    network: PreTrainedModel, ids: torch.Tensor, positions: torch.Tensor
) -> torch.Tensor:
    with torch.no_grad():
        return logits_at(network, ids, positions)


def kl_per_token(teacher: torch.Tensor, student: torch.Tensor) -> torch.Tensor:
    return functional.kl_div(
        functional.log_softmax(student, dim=-1),
        functional.log_softmax(teacher, dim=-1),
        reduction="none",
        log_target=True,
    ).sum(-1)
