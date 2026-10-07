from dataclasses import replace

import pytest
from fakes.model import FakeModel
from fakes.tokenizer import synthetic_prompt_tokenizer

from gisting.agent.assemble import Loaded, assemble_deps, production_tools
from gisting.agent.state import ToolRunner
from gisting.shopify.demo_apply import UsageError
from gisting.shopify.jsonvalue import JsonObject
from gisting.tools.lookup_order import ToolResponse
from gisting.tools.policy import load_policy


class FakeTool:
    def call(self, arguments: JsonObject, session_id: str) -> ToolResponse:
        raise AssertionError


def loaded(gist_count: int | None = None, run_id: str | None = None) -> Loaded:
    return Loaded(FakeModel([]), synthetic_prompt_tokenizer(), gist_count, run_id, {"id": "x"})


def test_production_tools_are_exactly_the_three_frozen_names() -> None:
    lookup = FakeTool()
    tools = production_tools(lookup)
    assert set(tools) == {"lookup_order", "handoff_to_human", "send_shipping_reminder"}
    assert tools["lookup_order"] is lookup


def test_assembled_deps_carry_the_given_tools_mode_and_identity() -> None:
    tools: dict[str, ToolRunner] = {"lookup_order": FakeTool()}
    base = loaded()
    deps = assemble_deps(base, "full", tools, load_policy())
    assert deps.tools is tools
    assert deps.mode == "full"
    assert deps.gist_run_id is None
    assert deps.model is base.model
    assert deps.identity == {"id": "x"}


def test_gist_mode_takes_the_run_id_and_full_mode_drops_it() -> None:
    tools = production_tools(FakeTool())
    gist = assemble_deps(loaded(4, "run-1"), "gist", tools, load_policy())
    assert (gist.mode, gist.gist_run_id) == ("gist", "run-1")
    full = assemble_deps(loaded(4, "run-1"), "full", tools, load_policy())
    assert (full.mode, full.gist_run_id) == ("full", None)
    assert gist.rules != full.rules


def test_gist_mode_without_a_loaded_gist_is_a_usage_error() -> None:
    with pytest.raises(UsageError, match="needs a loaded Gist artifact"):
        assemble_deps(loaded(), "gist", production_tools(FakeTool()), load_policy())


def test_assembled_deps_carry_the_given_lookup_policy_not_the_default() -> None:
    custom = replace(load_policy(), failure_limit=load_policy().failure_limit + 1)
    deps = assemble_deps(loaded(), "full", production_tools(FakeTool()), custom)
    assert deps.lookup is custom
