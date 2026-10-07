import json
from collections import defaultdict, deque
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fakes.model import FakeModel
from fakes.tokenizer import synthetic_prompt_tokenizer

from gisting.agent.policy import load_agent_policy
from gisting.agent.state import AgentDeps, ToolRunner
from gisting.agent.turn import run_turn
from gisting.eval.case_files import load_cases, plan_orders
from gisting.eval.case_spec import EvalCase
from gisting.eval.redact import Redactor
from gisting.eval.slots import fill_case, fill_text
from gisting.prompt.assemble import full_rules, tools_segment
from gisting.prompt.messages import AssistantMessage, Message, UserMessage
from gisting.prompt.schema import load_tool_schemas
from gisting.shopify.jsonvalue import JsonObject
from gisting.tools.lookup_order import ToolResponse
from gisting.tools.policy import load_policy
from gisting.tools.trace import InternalTrace, PublicOutcome, PublicTrace, Trace

IDENTITY = ("backend_id", "gist_run_id", "mode", "model")
ROOT = Path(__file__).resolve().parents[2]
SESSION_EMAIL = "customer{order}@example.com"
REUSED = "reused"


class Diverged(RuntimeError):
    pass


@dataclass
class RecordedTool:
    queue: deque[ToolResponse]

    def call(self, arguments: JsonObject, session_id: str) -> ToolResponse:
        if not self.queue:
            message = "the replay needs a tool result the original run did not have"
            raise Diverged(message)
        return self.queue.popleft()


def recorded_responses(row: Mapping[str, Any]) -> dict[str, deque[ToolResponse]]:
    public = iter(row["trace"]["tools"])
    found: dict[str, deque[ToolResponse]] = defaultdict(deque)
    for call in row["internal"]["tool_calls"]:
        trace = call["trace"]
        if call["problem"] is not None or trace is None or trace.get(REUSED):
            continue
        shown = next(public)
        internal = InternalTrace(
            trace["tool"],
            trace["session_id"],
            trace["order_number"],
            trace["result_type"],
            trace["cache_hit"],
            trace["detail"],
            trace["failures_before"],
        )
        outer = PublicTrace(shown["tool"], shown["order_number"], PublicOutcome(shown["outcome"]))
        found[call["name"]].append(ToolResponse(json.loads(call["result"]), Trace(internal, outer)))
    return found


def build_deps(row: Mapping[str, Any], outputs: list[str]) -> AgentDeps:
    tokenizer, schemas = synthetic_prompt_tokenizer(), load_tool_schemas()
    responses = recorded_responses(row)
    tools: dict[str, ToolRunner] = {
        name: RecordedTool(responses[name])
        for name in ("lookup_order", "handoff_to_human", "send_shipping_reminder")
    }
    return AgentDeps(
        FakeModel(outputs),
        tokenizer,
        tools,
        schemas,
        full_rules(tokenizer),
        tools_segment(tokenizer, schemas.values()),
        load_agent_policy(),
        load_policy(),
        row["mode"],
    )


def history_of(case: EvalCase) -> tuple[list[Message], dict[str, str]]:
    found = plan_orders(ROOT, case.fixtures.plan or "")
    plan = [item.order for item in found or []]
    email_of = {order: SESSION_EMAIL.format(order=order.strip("#")) for order in plan}
    filled = fill_case(case, plan, email_of)
    messages: list[Message] = [
        UserMessage(m["content"]) if m["role"] == "user" else AssistantMessage(m["content"])
        for m in filled.messages
    ]
    return messages, filled.emails


def cases_by_id() -> dict[str, EvalCase]:
    loaded, _ = load_cases(ROOT)
    return {item.case.id: item.case for item in loaded}


def replay_row(row: Mapping[str, Any], case: EvalCase) -> dict[str, Any]:
    messages, emails = history_of(case)
    outputs = [
        fill_text(case.id, call["raw_output"], emails) for call in row["internal"]["model_calls"]
    ]
    result = run_turn(build_deps(row, outputs), case.id, messages)
    redactor = Redactor(emails)
    document = json.loads(redactor.apply(json.dumps(result.traces.internal)))
    public = json.loads(redactor.apply(json.dumps(result.traces.public)))
    return {
        **row,
        "answer": redactor.apply(result.answer),
        "internal": {**document, **{key: row["internal"][key] for key in IDENTITY}},
        "trace": public,
    }
