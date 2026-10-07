import pytest
from fakes.tiny_qwen import random_gist, tiny_model
from fakes.tokenizer import synthetic_prompt_tokenizer
from gist_support import gist_prompt

from gisting.manifest.record import GistManifest
from gisting.model_server.gist import GistInjectionError
from gisting.prompt.assemble import assemble, full_rules, tools_segment
from gisting.prompt.messages import UserMessage
from gisting.prompt.schema import load_tool_schemas

TOKENIZER = synthetic_prompt_tokenizer()
NEW_TOKENS = 6
MANIFEST = GistManifest(
    "run-1", "rev1", "b" * 64, "c" * 64, "d" * 64, 16, 32, 700, "e" * 64, "f" * 64, "cpu", "a" * 64
)


def full_prompt(text: str = "Where is order #1042?") -> list[int]:
    tools = tools_segment(TOKENIZER, load_tool_schemas().values())
    return assemble(TOKENIZER, full_rules(TOKENIZER), tools, [UserMessage(text)]).ids


def test_a_model_with_a_gist_attached_refuses_a_full_prompt() -> None:
    model = tiny_model(random_gist(TOKENIZER))
    with pytest.raises(GistInjectionError, match="0 gist placeholders but 4"):
        model.generate(full_prompt(), 2)


def test_the_view_serves_a_full_prompt_like_a_model_that_never_had_a_gist() -> None:
    view = tiny_model(random_gist(TOKENIZER)).without_gist()
    never_attached = tiny_model()
    assert view.generate(full_prompt(), NEW_TOKENS).ids == (
        never_attached.generate(full_prompt(), NEW_TOKENS).ids
    )


def test_the_view_shares_the_loaded_weights_instead_of_copying_them() -> None:
    model = tiny_model(random_gist(TOKENIZER))
    view = model.without_gist()
    assert view.network is model.network
    assert view.backend_id == model.backend_id
    assert view.stop_ids == model.stop_ids
    assert view.gist is None
    assert view.gist_manifest is None


def test_taking_the_view_leaves_the_original_gist_intact_for_the_single_flight_gate() -> None:
    gist = random_gist(TOKENIZER)
    model = tiny_model(gist)
    expected = tiny_model(random_gist(TOKENIZER)).generate(gist_prompt(TOKENIZER), NEW_TOKENS).ids
    model.without_gist()
    assert model.gist is gist
    assert model.generate(gist_prompt(TOKENIZER), NEW_TOKENS).ids == expected


def test_taking_the_view_keeps_the_manifest_on_the_model_and_clears_it_on_the_view() -> None:
    model = tiny_model(random_gist(TOKENIZER))
    model.gist_manifest = MANIFEST
    view = model.without_gist()
    assert view.gist_manifest is None
    assert model.gist_manifest is MANIFEST


def test_the_view_shares_every_field_except_the_gist_pair_and_the_stop_ids_are_frozen() -> None:
    model = tiny_model(random_gist(TOKENIZER))
    view = model.without_gist()
    shared = set(vars(model)) - {"gist", "gist_manifest"}
    assert set(vars(view)) == set(vars(model))
    assert all(vars(view)[name] is vars(model)[name] for name in shared)
    assert isinstance(view.stop_ids, frozenset)
