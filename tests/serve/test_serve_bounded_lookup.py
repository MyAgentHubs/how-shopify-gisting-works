import time
from dataclasses import dataclass, replace
from pathlib import Path

import pytest
from fakes.http_shopify import Stall, running_shop
from loading_support import serve_env
from runner_support import GOOD_EMAIL, SECRET, SESSION, Rig, asking, lookup_call, lookup_parts

from gisting.agent.policy import load_agent_policy
from gisting.prompt.messages import AssistantMessage, Message, UserMessage
from gisting.serve.config import LIMITS
from gisting.serve.deadline import Deadline, DeadlineExceeded
from gisting.serve.loading import load_lookup
from gisting.serve.lookups import LookupReads
from gisting.serve.scope import TurnScope
from gisting.shopify.http_transport import HttpConfig, HttpTransport
from gisting.shopify.results import Result, Uncertain
from gisting.shopify.transport import Request
from gisting.tools.attempts import InMemoryFailureCounter
from gisting.tools.handoff import TOOL_NAME as HANDOFF
from gisting.tools.policy import load_policy
from gisting.tools.reads import DISCARD, LookupRead

BUDGET_S = 10.0
STALL_S = 8.0
REAL_BUDGET_S = 0.6
RECOVERY_S = 4.0
LEFT_S = 0.2


@dataclass
class Clock:
    now: float = 0.0

    def __call__(self) -> float:
        return self.now


@dataclass
class Slow:
    clock: Clock
    each_call_takes: float
    store: str = "gisting-lab.myshopify.com"
    calls: int = 0

    def execute(self, request: Request) -> Result:
        self.calls += 1
        self.clock.now += self.each_call_takes
        return Uncertain("timed out")


def counter() -> InMemoryFailureCounter:
    return InMemoryFailureCounter(load_policy().failure_limit)


def agreed_handoff() -> list[Message]:
    offer = load_agent_policy().consent_guards[HANDOFF].offer_text
    return [UserMessage("it is late"), AssistantMessage(f"Sorry. {offer}"), UserMessage("yes")]


def test_a_slow_read_stops_the_turn_before_the_retry_instead_of_waiting_it_out() -> None:
    clock = Clock()
    transport = Slow(clock, each_call_takes=BUDGET_S + 1)
    rig = Rig(lookup=lookup_parts(transport))
    rig.full_model.outputs.append(lookup_call(GOOD_EMAIL))
    with pytest.raises(DeadlineExceeded):
        rig.runner(
            "full",
            SESSION,
            asking(GOOD_EMAIL),
            TurnScope(Deadline(BUDGET_S, clock), counter(), DISCARD),
        )
    assert transport.calls == 1


def test_the_retry_pause_is_cut_to_what_is_left_of_the_budget() -> None:
    clock = Clock()
    transport = Slow(clock, each_call_takes=BUDGET_S - LEFT_S)
    slept: list[float] = []

    def sleep(seconds: float) -> None:
        slept.append(seconds)
        clock.now += seconds

    rig = Rig(lookup=lookup_parts(transport, sleep))
    rig.full_model.outputs.append(lookup_call(GOOD_EMAIL))
    with pytest.raises(DeadlineExceeded):
        rig.runner(
            "full",
            SESSION,
            asking(GOOD_EMAIL),
            TurnScope(Deadline(BUDGET_S, clock), counter(), DISCARD),
        )
    assert slept == pytest.approx([LEFT_S])
    assert transport.calls == 1


def test_an_expired_deadline_stops_the_code_path_before_any_tool_runs() -> None:
    rig = Rig()
    with pytest.raises(DeadlineExceeded):
        rig.runner(
            "full",
            SESSION,
            agreed_handoff(),
            TurnScope(Deadline(1.0, lambda: 2.0), counter(), DISCARD),
        )
    assert rig.full_model.prompts == []


def test_the_code_path_runs_normally_inside_the_budget() -> None:
    rig = Rig()
    result = rig.runner(
        "full", SESSION, agreed_handoff(), TurnScope(Deadline(9.0, lambda: 0.0), counter(), DISCARD)
    )
    assert result.traces.internal["reply_source"] == "code"
    assert rig.full_model.prompts == []


def test_a_normal_lookup_inside_the_budget_is_unaffected() -> None:
    rig = Rig()
    rig.full_model.outputs.append(lookup_call(GOOD_EMAIL))
    result = rig.runner(
        "full",
        SESSION,
        asking(GOOD_EMAIL),
        TurnScope(Deadline(BUDGET_S, lambda: 0.0), counter(), DISCARD),
    )
    assert result.fallback_reason is None
    assert len(rig.fake.calls) == 1


def test_the_worker_is_free_again_soon_after_a_stalled_shopify_read(tmp_path: Path) -> None:
    with running_shop() as (fake, url):
        fake.script = [Stall(STALL_S)] * 4

        def make(secret: str, config: HttpConfig) -> HttpTransport:
            return HttpTransport(secret, replace(config, base_url=url))

        env = replace(serve_env(tmp_path), email_secret=SECRET)
        rig = Rig(lookup=load_lookup(env, LIMITS, make))
        rig.full_model.outputs.append(lookup_call(GOOD_EMAIL))
        started = time.monotonic()
        deadline = Deadline(started + REAL_BUDGET_S, time.monotonic)
        with pytest.raises(DeadlineExceeded):
            rig.runner("full", SESSION, asking(GOOD_EMAIL), TurnScope(deadline, counter(), DISCARD))
        assert time.monotonic() - started < RECOVERY_S


def test_a_read_cut_off_by_the_deadline_is_reported_with_the_deadline_error_type() -> None:
    clock = Clock()
    rig = Rig(lookup=lookup_parts(Slow(clock, each_call_takes=BUDGET_S + 1)))
    rig.full_model.outputs.append(lookup_call(GOOD_EMAIL))
    reads = LookupReads(clock)
    with pytest.raises(DeadlineExceeded):
        rig.runner(
            "full",
            SESSION,
            asking(GOOD_EMAIL),
            TurnScope(Deadline(BUDGET_S, clock), counter(), reads),
        )
    assert reads.snapshot() == (LookupRead((BUDGET_S + 1) * 1000, "DeadlineExceeded", False),)


def test_a_cut_off_read_does_not_count_against_the_failure_lock() -> None:
    clock = Clock()
    rig = Rig(lookup=lookup_parts(Slow(clock, each_call_takes=BUDGET_S + 1)))
    rig.full_model.outputs.append(lookup_call(GOOD_EMAIL))
    failures = counter()
    with pytest.raises(DeadlineExceeded):
        rig.runner(
            "full",
            SESSION,
            asking(GOOD_EMAIL),
            TurnScope(Deadline(BUDGET_S, clock), failures, LookupReads(clock)),
        )
    assert failures.failures(SESSION) == 0
