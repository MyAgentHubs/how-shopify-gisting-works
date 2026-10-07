import json
from typing import Any

import pytest
from agent_support import (
    CANARY,
    EMAIL,
    NUMBER,
    SECRET,
    SESSION,
    public_of,
    rig,
    tool_call,
)

from gisting.agent.trace import GenerationRecord, Recorder, RunContext, build_traces
from gisting.prompt.messages import UserMessage
from gisting.prompt.segments import PromptStats

WRONG = "wrong@example.com"
GOOD = tool_call(order_number=f"#{NUMBER}", email=EMAIL)
BAD_EMAIL = tool_call(order_number=f"#{NUMBER}", email=WRONG)
UNKNOWN = tool_call(order_number="#9999", email=EMAIL)
TWO = GOOD + GOOD


def stats(history: int, results: int) -> PromptStats:
    return PromptStats(100, 50, history, results, 150 + history + results)


def traces_of(*prompts: PromptStats) -> dict[str, Any]:
    recorder = Recorder()
    for prompt in prompts:
        recorder.generations.append(GenerationRecord(prompt, "x", 1, 1.0, 2.0, "stop"))
    built = build_traces(recorder, RunContext("fake"), 3.0, None)
    return json.loads(json.dumps(built.public))


def test_the_public_tokens_never_carry_a_tool_result_part() -> None:
    tokens = traces_of(stats(10, 0), stats(12, 40))["tokens"]
    assert tokens["tool_results"] == 0
    assert tokens["history"] == 22 + 40
    assert tokens["total"] == 100 * 2 + 50 * 2 + 22 + 40
    assert tokens["rules"] + tokens["tools"] + tokens["history"] == tokens["total"]


@pytest.mark.parametrize("results", [0, 7, 834])
def test_the_public_tokens_do_not_change_shape_with_the_size_of_a_tool_result(
    results: int,
) -> None:
    assert set(traces_of(stats(10, results))["tokens"]) == {
        "rules",
        "tools",
        "history",
        "tool_results",
        "total",
    }
    assert traces_of(stats(10, results))["tokens"]["tool_results"] == 0


def public_projection(calls: list[str], message: str) -> dict[str, Any]:
    subject = rig(*calls, "x", max_tool_calls=2)
    result = subject.run([UserMessage(message)])
    projection = public_of(result)
    projection.pop("latency")
    return projection


def echo_free(projection: dict[str, Any]) -> dict[str, Any]:
    tokens = projection["tokens"]
    return {
        "tools": projection["tools"],
        "tokens": {k: v for k, v in tokens.items() if k != "history" and k != "total"},
    }


ANY = f"Where is order #{NUMBER} or #9999? My email is {EMAIL} or {WRONG}"


@pytest.mark.parametrize(
    "outputs",
    [
        [TWO, GOOD],
        [TWO, BAD_EMAIL],
        [TWO, UNKNOWN],
        [GOOD + BAD_EMAIL, GOOD],
        [BAD_EMAIL + BAD_EMAIL, BAD_EMAIL],
    ],
)
def test_whatever_the_lookups_found_the_public_projection_is_the_same(outputs: list[str]) -> None:
    baseline = public_projection([TWO, GOOD], ANY)
    projection = public_projection(outputs, ANY)
    assert echo_free(projection)["tokens"] == echo_free(baseline)["tokens"]
    assert projection["tokens"]["tool_results"] == 0


@pytest.mark.parametrize("call", [GOOD, BAD_EMAIL, UNKNOWN])
def test_a_found_a_mismatched_and_an_unknown_order_look_the_same_in_the_public_trace(
    call: str,
) -> None:
    projection = public_projection([call], ANY)
    assert [t["outcome"] for t in projection["tools"]] == ["completed"]
    assert projection["tokens"]["tool_results"] == 0
    assert set(projection) == {"tools", "knowledge", "tokens"}
    text = json.dumps(projection)
    for hidden in (CANARY, SECRET, SESSION, "found", "no_match", "Mismatch", "verified"):
        assert hidden not in text
