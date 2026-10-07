from dataclasses import replace
from pathlib import Path

import pytest
from fakes.tiny_qwen import HIDDEN, K, random_gist, tiny_model, torch
from fakes.tokenizer import synthetic_prompt_tokenizer
from gist_support import gist_prompt, setup_artifact

from gisting.manifest.record import GIST_FILE, ManifestError, sha256_file, write_manifest
from gisting.manifest.verify import ManifestMismatch
from gisting.model_server.gist import (
    GistInjection,
    GistInjectionError,
    embed_with_gist,
    parameters_sha256,
)
from gisting.model_server.gist_store import read_gist, write_gist

TOKENIZER = synthetic_prompt_tokenizer()
PLACEHOLDER = TOKENIZER.gist_placeholder


def test_placeholder_positions_are_replaced_by_the_gist_vectors_in_order() -> None:
    model = tiny_model()
    gist = random_gist(TOKENIZER)
    ids = gist_prompt(TOKENIZER)
    embeds = embed_with_gist(
        model.network.get_input_embeddings(), torch.tensor([ids]), PLACEHOLDER, gist
    )
    positions = [index for index, token in enumerate(ids) if token == PLACEHOLDER]
    assert len(positions) == K
    assert torch.equal(embeds[0, positions], gist.vectors)
    plain = model.network.get_input_embeddings()(torch.tensor([ids]))
    others = [index for index in range(len(ids)) if index not in positions]
    assert torch.equal(embeds[0, others], plain[0, others])


def test_injection_leaves_every_base_parameter_unchanged_including_the_tied_head() -> None:
    gist = random_gist(TOKENIZER)
    model = tiny_model(gist)
    assert model.network.lm_head.weight is model.network.get_input_embeddings().weight
    before = parameters_sha256(model.network)
    model.generate(gist_prompt(TOKENIZER), 6)
    assert parameters_sha256(model.network) == before
    assert not model.network.get_input_embeddings().weight[PLACEHOLDER].equal(gist.vectors[0])


def test_the_hash_notices_a_changed_parameter() -> None:
    model = tiny_model()
    before = parameters_sha256(model.network)
    with torch.no_grad():
        model.network.get_input_embeddings().weight[3, 0] += 1.0
    assert parameters_sha256(model.network) != before


def test_generation_with_a_gist_equals_greedy_decoding_over_the_injected_embeddings() -> None:
    gist = random_gist(TOKENIZER)
    model = tiny_model(gist)
    ids = gist_prompt(TOKENIZER)
    embeds = embed_with_gist(
        model.network.get_input_embeddings(), torch.tensor([ids]), PLACEHOLDER, gist
    )
    expected = model.network.generate(
        inputs_embeds=embeds, max_new_tokens=8, do_sample=False, min_new_tokens=8
    )
    model.stop_ids = frozenset()
    assert list(model.generate(ids, 8).ids) == [int(token) for token in expected[0]]


def test_a_gist_changes_the_output_distribution_compared_with_no_gist_vectors() -> None:
    model = tiny_model(random_gist(TOKENIZER, seed=1))
    other = tiny_model(random_gist(TOKENIZER, seed=2))
    ids = gist_prompt(TOKENIZER)
    first = embed_with_gist(
        model.network.get_input_embeddings(), torch.tensor([ids]), PLACEHOLDER, model.gist
    )
    second = embed_with_gist(
        other.network.get_input_embeddings(), torch.tensor([ids]), PLACEHOLDER, other.gist
    )
    assert not torch.equal(first, second)


def test_placeholders_without_loaded_vectors_fail_fast() -> None:
    with pytest.raises(GistInjectionError, match="4 gist placeholders but 0"):
        tiny_model().generate(gist_prompt(TOKENIZER), 2)


def test_a_placeholder_count_that_differs_from_the_vector_count_fails_fast() -> None:
    gist = GistInjection(torch.zeros(K + 1, HIDDEN), PLACEHOLDER)
    with pytest.raises(GistInjectionError, match="4 gist placeholders but 5"):
        tiny_model(gist).generate(gist_prompt(TOKENIZER), 2)


def test_vectors_without_placeholders_fail_fast() -> None:
    model = tiny_model(random_gist(TOKENIZER))
    plain = TOKENIZER.encode_text("hello")
    with pytest.raises(GistInjectionError, match="0 gist placeholders but 4"):
        model.generate(plain, 2)


def test_gist_artifact_loads_and_generates_the_same_tokens(tmp_path: Path) -> None:
    directory, model_dir, _ = setup_artifact(tmp_path)
    served = tiny_model()
    served.attach_gist(directory, model_dir)
    assert served.gist_manifest is not None
    assert served.gist_manifest.run_id == "run-test"
    ids = gist_prompt(TOKENIZER)
    assert served.generate(ids, 6).ids == tiny_model(random_gist(TOKENIZER)).generate(ids, 6).ids


def test_gist_artifact_for_another_backend_is_refused(tmp_path: Path) -> None:
    directory, model_dir, _ = setup_artifact(tmp_path, "transformers-mps-bfloat16")
    with pytest.raises(ManifestMismatch, match="backend_id"):
        tiny_model().attach_gist(directory, model_dir)


def test_gist_artifact_with_a_changed_base_model_is_refused(tmp_path: Path) -> None:
    directory, model_dir, _ = setup_artifact(tmp_path)
    (model_dir / "SHA256SUMS").write_text("1" * 64 + "  model.safetensors\n")
    with pytest.raises(ManifestMismatch, match="base_model_sha256"):
        tiny_model().attach_gist(directory, model_dir)


def test_gist_artifact_with_a_tampered_tensor_file_is_refused(tmp_path: Path) -> None:
    directory, model_dir, _ = setup_artifact(tmp_path)
    write_gist(directory, random_gist(TOKENIZER, seed=9).vectors)
    with pytest.raises(ManifestMismatch, match="gist_sha256"):
        tiny_model().attach_gist(directory, model_dir)


def test_gist_artifact_with_the_wrong_shape_is_refused(tmp_path: Path) -> None:
    directory, model_dir, manifest = setup_artifact(tmp_path)
    write_gist(directory, torch.zeros(K + 1, HIDDEN))
    resealed = replace(manifest, gist_sha256=sha256_file(directory / GIST_FILE))
    write_manifest(directory, resealed)
    with pytest.raises(ManifestError, match="manifest says"):
        tiny_model().attach_gist(directory, model_dir)


def test_gist_tensor_round_trips_in_float32(tmp_path: Path) -> None:
    vectors = random_gist(TOKENIZER).vectors
    write_gist(tmp_path, vectors.to(torch.bfloat16))
    loaded = read_gist(tmp_path)
    assert loaded.dtype == torch.float32
    assert torch.equal(loaded, vectors.to(torch.bfloat16).to(torch.float32))


def test_a_missing_gist_tensor_file_is_a_manifest_error(tmp_path: Path) -> None:
    with pytest.raises(ManifestError, match="cannot read gist vectors"):
        read_gist(tmp_path)
