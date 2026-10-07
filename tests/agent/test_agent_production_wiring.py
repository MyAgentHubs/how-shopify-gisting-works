from pathlib import Path

import pytest
from agent_support import SECRET, demo_order
from fakes.model import FakeModel
from fakes.shopify import FakeTransport
from fakes.tokenizer import synthetic_prompt_tokenizer

from gisting.agent.cli import Runtime, build_deps, build_parser
from gisting.tools.cli import Runtime as ToolsRuntime

PRODUCTION_TOOLS = {"lookup_order", "handoff_to_human", "send_shipping_reminder"}


@pytest.fixture(autouse=True)
def secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GISTING_EMAIL_SECRET", SECRET)


def test_the_production_assembly_runs_exactly_the_three_order_tools(tmp_path: Path) -> None:
    env_file = tmp_path / "empty.env"
    env_file.write_text("")
    args = build_parser().parse_args(["run", "--env-file", str(env_file)])
    runtime = Runtime(
        ToolsRuntime(FakeTransport([demo_order()]), lambda _seconds: None),
        FakeModel([]),
        synthetic_prompt_tokenizer(),
    )
    deps = build_deps(args, runtime)
    assert set(deps.tools) == PRODUCTION_TOOLS
    assert set(deps.schemas) == PRODUCTION_TOOLS
    assert not deps.policy_answers
    assert not deps.policy_ids
