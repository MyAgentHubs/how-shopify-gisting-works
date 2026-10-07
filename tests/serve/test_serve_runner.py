from collections.abc import Iterable, Mapping
from dataclasses import replace

import pytest
from runner_support import (
    GOOD_EMAIL,
    NUMBER,
    SESSION,
    WRONG_EMAIL,
    Rig,
    asking,
    expired_deadline,
    greeting,
    lookup_call,
    open_deadline,
)

import gisting.serve.runner as runner_module
from gisting.agent.assemble import Loaded, assemble_deps
from gisting.agent.state import AgentDeps, ToolRunner
from gisting.serve.contract import Mode
from gisting.serve.deadline import DeadlineExceeded
from gisting.serve.runner import FROZEN_TOOLS, ToolSetMismatch
from gisting.serve.scope import TurnScope
from gisting.shopify.results import Cause, NotExecuted
from gisting.tools.attempts import InMemoryFailureCounter
from gisting.tools.policy import LookupPolicy, load_policy
from gisting.tools.reads import DISCARD

FAILURE_LIMIT = load_policy().failure_limit
REMINDER = "send_shipping_reminder"


def test_the_frozen_tool_set_is_the_three_order_tools() -> None:
    expected = {"lookup_order", "handoff_to_human", "send_shipping_reminder"}
    assert expected == FROZEN_TOOLS


@pytest.mark.parametrize("mode", ["gist", "full"])
def test_each_mode_runs_on_its_own_base_deps(mode: Mode) -> None:
    rig = Rig()
    rig.gist_model.outputs.append("Hello, how can I help?")
    rig.full_model.outputs.append("Hello, how can I help?")
    result = rig.runner(
        mode,
        SESSION,
        greeting(),
        TurnScope(open_deadline(), InMemoryFailureCounter(FAILURE_LIMIT), DISCARD),
    )
    used, unused = (
        (rig.gist_model, rig.full_model) if mode == "gist" else (rig.full_model, rig.gist_model)
    )
    assert len(used.prompts) == 1
    assert unused.prompts == []
    assert result.traces.internal["mode"] == mode


def test_assemble_deps_runs_only_when_the_runner_is_made(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def counting(*args: object, **kwargs: object):
        calls.append("assemble")
        return assemble_deps(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(runner_module, "assemble_deps", counting)
    rig = Rig()
    assert len(calls) == 2
    for mode in ("gist", "full", "gist"):
        rig.full_model.outputs.append("Hello.")
        rig.gist_model.outputs.append("Hello.")
        rig.runner(
            mode,
            SESSION,
            greeting(),
            TurnScope(open_deadline(), InMemoryFailureCounter(3), DISCARD),
        )
    assert len(calls) == 2


def test_the_passed_failure_counter_is_the_one_lookup_uses() -> None:
    rig = Rig()
    rig.full_model.outputs.append(lookup_call(WRONG_EMAIL))
    counter = InMemoryFailureCounter(FAILURE_LIMIT)
    rig.runner("full", SESSION, asking(WRONG_EMAIL), TurnScope(open_deadline(), counter, DISCARD))
    assert counter.failures(SESSION) == 1


def test_each_request_counts_on_its_own_counter() -> None:
    rig = Rig()
    first, second = InMemoryFailureCounter(FAILURE_LIMIT), InMemoryFailureCounter(FAILURE_LIMIT)
    rig.full_model.outputs.append(lookup_call(WRONG_EMAIL))
    rig.runner("full", SESSION, asking(WRONG_EMAIL), TurnScope(open_deadline(), first, DISCARD))
    rig.full_model.outputs.append(lookup_call(GOOD_EMAIL))
    rig.runner("full", SESSION, asking(GOOD_EMAIL), TurnScope(open_deadline(), second, DISCARD))
    assert (first.failures(SESSION), second.failures(SESSION)) == (1, 0)


def test_an_expired_deadline_stops_the_turn_before_the_model_runs() -> None:
    rig = Rig()
    rig.gist_model.outputs.append("Hello.")
    with pytest.raises(DeadlineExceeded):
        rig.runner(
            "gist",
            SESSION,
            greeting(),
            TurnScope(expired_deadline(), InMemoryFailureCounter(3), DISCARD),
        )
    assert rig.gist_model.prompts == []


def test_the_base_deps_are_untouched_by_a_request() -> None:
    rig = Rig()
    gist, full = rig.runner.gist, rig.runner.full
    before = (gist, full, gist.model, full.model, gist.tools, full.tools)
    snapshot = (replace(gist), replace(full))
    rig.full_model.outputs.append(lookup_call(GOOD_EMAIL))
    rig.runner(
        "full",
        SESSION,
        asking(GOOD_EMAIL),
        TurnScope(open_deadline(), InMemoryFailureCounter(3), DISCARD),
    )
    after = (
        rig.runner.gist,
        rig.runner.full,
        rig.runner.gist.model,
        rig.runner.full.model,
        rig.runner.gist.tools,
        rig.runner.full.tools,
    )
    assert all(left is right for left, right in zip(before, after, strict=True))
    assert (rig.runner.gist, rig.runner.full) == snapshot
    assert gist.tools == {}
    assert full.tools == {}


def test_a_read_only_transport_keeps_mutations_from_the_underlying_transport() -> None:
    rig = Rig()
    rig.full_model.outputs.append(lookup_call(GOOD_EMAIL))
    rig.runner(
        "full",
        SESSION,
        asking(GOOD_EMAIL),
        TurnScope(open_deadline(), InMemoryFailureCounter(3), DISCARD),
    )
    assert rig.fake.calls
    client = rig.runner.lookup.client_for(open_deadline())
    state = client.fetch_order(f"#{NUMBER}")
    verified = client.writable(state)  # type: ignore[arg-type]
    assert not isinstance(verified, NotExecuted)
    written = client.write(verified, "tags_add", {"id": verified.order_id, "tags": ["x"]})
    assert written == NotExecuted(Cause.READ_ONLY, "tags_add")
    assert rig.fake.writes == []


def test_a_tool_set_other_than_the_frozen_three_is_refused_when_the_runner_is_built(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def only_lookup(lookup: ToolRunner) -> dict[str, ToolRunner]:
        return {"lookup_order": lookup}

    monkeypatch.setattr(runner_module, "production_tools", only_lookup)
    with pytest.raises(ToolSetMismatch, match="handoff_to_human"):
        Rig()


@pytest.mark.parametrize("mode", ["gist", "full"])
def test_a_schema_set_other_than_the_frozen_three_is_refused_when_the_runner_is_built(
    monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    def without_reminder(
        loaded: Loaded, which: str, tools: Mapping[str, ToolRunner], policy: LookupPolicy
    ) -> AgentDeps:
        deps = assemble_deps(loaded, which, tools, policy)
        if which != mode:
            return deps
        kept = {name: item for name, item in deps.schemas.items() if name != REMINDER}
        return replace(deps, schemas=kept)

    monkeypatch.setattr(runner_module, "assemble_deps", without_reminder)
    with pytest.raises(ToolSetMismatch, match=REMINDER):
        Rig()


def test_the_frozen_set_is_checked_when_the_runner_is_built_and_not_again_per_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int] = []
    original = runner_module.require_frozen_tools

    def counting(tools: Iterable[str], schemas: Iterable[str]) -> None:
        calls.append(1)
        original(tools, schemas)

    monkeypatch.setattr(runner_module, "require_frozen_tools", counting)
    rig = Rig()
    built = len(calls)
    assert built >= 1
    rig.gist_model.outputs.append("Hello.")
    rig.runner(
        "gist", SESSION, greeting(), TurnScope(open_deadline(), InMemoryFailureCounter(3), DISCARD)
    )
    assert len(calls) == built
