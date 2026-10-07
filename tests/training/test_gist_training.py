from dataclasses import replace
from typing import Any

import pytest
from fakes.tiny_qwen import K, tiny_model, torch
from torch_support import HPARAMS, TOKENIZER, examples, fresh_run, kit, pick, record

from gisting.model_server.gist import GistInjection, parameters_sha256
from gisting.model_server.transformers_backend import TransformersModel
from gisting.training.examples import make_example
from gisting.training.forward import kl_per_token, student_logits, teacher_logits
from gisting.training.gist_init import chunk_mean_init, initial_gist, random_init
from gisting.training.trainer import checkpointed, dev_kl, example_kl, train, train_batch


def test_one_step_changes_the_gist_vectors_and_no_other_parameter() -> None:
    model = tiny_model()
    run = fresh_run(model)
    before_gist = run.gist.detach().clone()
    before = parameters_sha256(model.network)
    optimizer = torch.optim.AdamW([run.gist], lr=HPARAMS.lr, weight_decay=0.0)
    train_batch(run, examples("train", 2), optimizer)
    assert not torch.equal(run.gist.detach(), before_gist)
    assert parameters_sha256(model.network) == before
    assert all(not parameter.requires_grad for parameter in model.network.parameters())
    assert run.gist.dtype == torch.float32
    assert run.gist.grad is not None
    assert all(parameter.grad is None for parameter in model.network.parameters())


def test_training_lowers_the_divergence_on_the_examples_it_trains_on() -> None:
    model = tiny_model()
    run = fresh_run(model)
    train_set = examples("train", 6)
    before = dev_kl(run, train_set)
    train(run, train_set, train_set)
    assert dev_kl(run, train_set) < before
    devs = [row["dev_kl"] for row in run.log if row["event"] == "dev"]
    assert len(devs) == HPARAMS.epochs + 1
    assert devs[0] == pytest.approx(before)
    steps = [row for row in run.log if row["event"] == "step"]
    assert len(steps) == 3 * HPARAMS.epochs


def test_serving_and_training_logits_agree_after_a_training_step() -> None:
    model = tiny_model()
    run = fresh_run(model)
    optimizer = torch.optim.AdamW([run.gist], lr=0.2, weight_decay=0.0)
    train_batch(run, examples("train", 2), optimizer)
    injection = GistInjection(run.gist.detach().clone(), TOKENIZER.gist_placeholder)
    model.gist = injection
    sample = pick("dev", 1)[0]
    prefix = kit().prompt(sample.messages, gist=True).ids
    served = model.generate(prefix, 6)
    sequence = torch.tensor([prefix + list(served.ids)])
    positions = torch.arange(len(prefix) - 1, sequence.shape[1] - 1)
    trained = student_logits(model.network, sequence, positions, injection)
    assert [int(token) for token in trained.argmax(-1)] == list(served.ids)
    incremental = incremental_logits(model, prefix, list(served.ids))
    assert torch.allclose(trained, incremental, atol=1e-4)


def incremental_logits(model: TransformersModel, prefix: list[int], continuation: list[int]):
    cache = None
    rows: list[Any] = []
    step = {"inputs_embeds": model.prefill_embeds(prefix)}
    with torch.no_grad():
        for token in [*continuation, None]:
            output = model.network(**step, past_key_values=cache, use_cache=True)
            cache = output.past_key_values
            rows.append(output.logits[0, -1].float())
            if token is not None:
                step = {"input_ids": torch.tensor([[token]])}
    return torch.stack(rows[: len(continuation)])


def test_kl_is_zero_for_equal_logits_and_matches_its_definition() -> None:
    generator = torch.Generator().manual_seed(3)
    teacher = torch.randn(5, 11, generator=generator)
    student = torch.randn(5, 11, generator=generator)
    assert torch.allclose(kl_per_token(teacher, teacher), torch.zeros(5), atol=1e-6)
    p, q = teacher.softmax(-1), student.softmax(-1)
    manual = (p * (p.log() - q.log())).sum(-1)
    assert torch.allclose(kl_per_token(teacher, student), manual, atol=1e-5)
    assert bool((kl_per_token(teacher, student) > 0).all())


def test_teacher_path_uses_plain_ids_and_never_sees_placeholders() -> None:
    model = tiny_model()
    sample = pick("train", 1)[0]
    item = make_example(kit(), record(sample), "cpu", 8192)
    assert item is not None
    assert all(int(t) != TOKENIZER.gist_placeholder for t in item.teacher_ids[0])
    assert sum(int(t) == TOKENIZER.gist_placeholder for t in item.student_ids[0]) == K
    logits = teacher_logits(model.network, item.teacher_ids, item.teacher_positions)
    assert logits.shape[0] == len(record(sample).ids) + 1
    assert not logits.requires_grad


def test_examples_longer_than_max_len_are_skipped() -> None:
    sample = pick("train", 1)[0]
    assert make_example(kit(), record(sample), "cpu", 10) is None


def test_kl_of_an_example_is_finite_and_positive_before_training() -> None:
    run = fresh_run(tiny_model())
    value = example_kl(run, examples("train", 1)[0])
    assert torch.isfinite(value)
    assert float(value.detach()) > 0


def test_chunk_mean_init_is_the_mean_of_contiguous_rules_embeddings() -> None:
    model = tiny_model()
    vectors = chunk_mean_init(model.network, kit(), K)
    assert tuple(vectors.shape) == (K, model.network.config.hidden_size)
    ids = torch.tensor(kit().full.ids)
    first = torch.tensor_split(model.network.get_input_embeddings()(ids).float(), K)[0].mean(0)
    assert torch.allclose(vectors[0], first.detach(), atol=1e-6)
    assert vectors.dtype == torch.float32


def test_random_init_is_seeded_and_scaled_like_the_embedding_table() -> None:
    model = tiny_model()
    first = random_init(model.network, K, 5)
    assert torch.equal(first, random_init(model.network, K, 5))
    assert not torch.equal(first, random_init(model.network, K, 6))
    scale = float(model.network.get_input_embeddings().weight.detach().std())
    assert 0.3 * scale < float(first.std()) < 3 * scale
    assert torch.equal(initial_gist(model.network, kit(), "random", 5, K), first)


def gist_gradient(checkpointing: bool) -> tuple[Any, float, bool, bool]:
    model = tiny_model()
    run = fresh_run(model, replace(HPARAMS, gradient_checkpointing=checkpointing))
    example = examples("train", 1)[0]
    with checkpointed(run):
        active = bool(model.network.is_gradient_checkpointing) and model.network.training
        loss = example_kl(run, example)
        loss.backward()
    assert run.gist.grad is not None
    return run.gist.grad.clone(), float(loss.detach()), active, model.network.training


def test_gradient_checkpointing_changes_the_memory_path_but_not_the_gradient() -> None:
    plain, plain_loss, plain_active, plain_mode = gist_gradient(False)
    saved, saved_loss, saved_active, saved_mode = gist_gradient(True)
    assert (plain_active, saved_active) == (False, True)
    assert (plain_mode, saved_mode) == (False, False)
    assert saved_loss == pytest.approx(plain_loss, abs=1e-6)
    assert torch.allclose(saved, plain, atol=1e-6)
    assert float(plain.abs().sum()) > 0


def test_a_run_with_checkpointing_on_still_lowers_the_divergence_and_leaves_the_base_alone() -> (
    None
):
    model = tiny_model()
    run = fresh_run(model, replace(HPARAMS, gradient_checkpointing=True))
    train_set = examples("train", 6)
    before, digest = dev_kl(run, train_set), parameters_sha256(model.network)
    train(run, train_set, train_set)
    assert dev_kl(run, train_set) < before
    assert parameters_sha256(model.network) == digest
    assert not model.network.training
