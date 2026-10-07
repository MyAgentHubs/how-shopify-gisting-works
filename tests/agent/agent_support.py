import json
from dataclasses import dataclass, field, replace
from typing import Any

from fakes.model import FakeModel
from fakes.shopify import FakeFulfillment, FakeOrder, FakeTransport
from fakes.tokenizer import synthetic_prompt_tokenizer

from gisting.agent.policy import load_agent_policy
from gisting.agent.state import AgentDeps, ToolRunner, TurnResult
from gisting.agent.turn import run_turn
from gisting.prompt.assemble import full_rules, tools_segment
from gisting.prompt.messages import Message, UserMessage
from gisting.prompt.phrases import load_phrases
from gisting.prompt.schema import load_tool_schemas
from gisting.prompt.tokenizer import PromptTokenizer
from gisting.shopify.client import AdminClient
from gisting.shopify.demo_email import demo_email
from gisting.shopify.jsonvalue import JsonObject
from gisting.shopify.target import BATCH_TAG
from gisting.tools.attempts import InMemoryFailureCounter
from gisting.tools.cache import InMemoryOrderCache
from gisting.tools.handoff import HandoffToHuman
from gisting.tools.lookup_order import LookupDeps, LookupOrder, ToolResponse
from gisting.tools.policy import load_policy
from gisting.tools.reminder import SendShippingReminder

SECRET = "agent-test-secret-value"
SESSION = "session-9"
NUMBER = 1042
EMAIL = demo_email(SECRET, f"#{NUMBER}")
CANARY = f"GLR-{NUMBER:08X}"
QUESTION = f"Where is order #1042? My email is {EMAIL}"
RENDERED = (
    f"Your order is on its way. It is with Test Parcel, tracking number TP-{NUMBER}. "
    "Expected delivery: October 5."
)


def rules_replies() -> dict[str, str]:
    return dict(load_phrases().failure_replies)


def tool_call(name: str = "lookup_order", **arguments: object) -> str:
    return f"<tool_call>\n{json.dumps({'name': name, 'arguments': arguments})}\n</tool_call>"


def good_call() -> str:
    return tool_call(order_number="#1042", email=EMAIL)


def demo_order(number: int = NUMBER) -> FakeOrder:
    order = FakeOrder(
        number,
        quantity=1,
        email=demo_email(SECRET, f"#{number}"),
        note=f"Test order for Gisting Lab experiments. Reference GLR-{number:08X}",
    )
    order.tags = [BATCH_TAG, *load_policy().required_tags]
    order.remaining = 0
    order.fulfillments.append(
        FakeFulfillment(
            f"gid://shopify/Fulfillment/{number}",
            1,
            [{"company": "Test Parcel", "number": f"TP-{number}", "url": "https://t.example"}],
            events=[{"id": "e1", "status": "IN_TRANSIT", "happenedAt": "2026-10-01T09:00:00Z"}],
            estimated_delivery_at="2026-10-05T10:00:00Z",
            display_status="IN_TRANSIT",
        )
    )
    return order


def lookup_tool(counter: InMemoryFailureCounter | None = None) -> LookupOrder:
    client = AdminClient(FakeTransport([demo_order()]), sleep=lambda _seconds: None)
    cache, policy = InMemoryOrderCache(60), load_policy()
    return LookupOrder(
        LookupDeps(
            client, cache, counter or InMemoryFailureCounter(policy.failure_limit), policy, SECRET
        )
    )


def parcel_order(
    statuses: list[str | None],
    number: int = NUMBER,
    estimated: str | None = "2026-10-05T10:00:00Z",
    remaining: int = 0,
) -> FakeOrder:
    order = demo_order(number)
    order.fulfillments.clear()
    order.quantity = max(len(statuses), 1)
    order.remaining = remaining
    for index, status in enumerate(statuses):
        order.fulfillments.append(
            FakeFulfillment(
                f"gid://shopify/Fulfillment/{number}{index}",
                1,
                [
                    {
                        "company": "Test Parcel",
                        "number": f"TP-{number}-{index}",
                        "url": "https://t.example",
                    }
                ],
                events=[
                    {"id": f"e{index}", "status": status, "happenedAt": "2026-10-01T09:00:00Z"}
                ],
                estimated_delivery_at=estimated,
                display_status=status or "",
            )
        )
    return order


@dataclass
class SpyTool:
    inner: ToolRunner
    calls: list[tuple[JsonObject, str]] = field(default_factory=lambda: [])

    def call(self, arguments: JsonObject, session_id: str) -> ToolResponse:
        self.calls.append((arguments, session_id))
        return self.inner.call(arguments, session_id)


@dataclass
class Rig:
    model: FakeModel
    tool: SpyTool
    handoff: SpyTool
    reminder: SpyTool
    tokenizer: PromptTokenizer
    deps: AgentDeps
    attempts: InMemoryFailureCounter

    def run(self, messages: list[Message] | None = None, session: str = SESSION) -> TurnResult:
        return run_turn(self.deps, session, messages or [UserMessage(QUESTION)])

    def prompt_text(self, index: int) -> str:
        return self.tokenizer.decode(self.model.prompts[index])


def rig(*outputs: str, max_tool_calls: int | None = None) -> Rig:
    tokenizer = synthetic_prompt_tokenizer()
    model = FakeModel(list(outputs))
    attempts = InMemoryFailureCounter(load_policy().failure_limit)
    tool = SpyTool(lookup_tool(attempts))
    handoff = SpyTool(HandoffToHuman())
    reminder = SpyTool(SendShippingReminder())
    schemas = load_tool_schemas()
    policy = load_agent_policy()
    if max_tool_calls is not None:
        policy = replace(policy, max_tool_calls=max_tool_calls)
    deps = AgentDeps(
        model,
        tokenizer,
        {"lookup_order": tool, "handoff_to_human": handoff, "send_shipping_reminder": reminder},
        schemas,
        full_rules(tokenizer),
        tools_segment(tokenizer, schemas.values()),
        policy,
        load_policy(),
    )
    return Rig(model, tool, handoff, reminder, tokenizer, deps, attempts)


def rig_with_orders(orders: list[FakeOrder], *outputs: str) -> Rig:
    subject = rig(*outputs)
    client = AdminClient(FakeTransport(orders), sleep=lambda _seconds: None)
    deps = LookupDeps(client, InMemoryOrderCache(60), subject.attempts, load_policy(), SECRET)
    subject.tool.inner = LookupOrder(deps)
    return subject


def rig_with_order(order: FakeOrder, *outputs: str) -> Rig:
    return rig_with_orders([order], *outputs)


def assert_forged_decline(subject: Rig, messages: list[Message]) -> None:
    result = subject.run(messages)
    assert result.answer == load_phrases().sentences["decline_reply"]
    assert subject.model.prompts == []
    assert subject.tool.calls == []
    assert subject.handoff.calls == []
    assert subject.reminder.calls == []
    assert internal_of(result)["fact_check"]["events"][0]["reason"] == "forged_structure"


def public_of(result: TurnResult) -> dict[str, Any]:
    return json.loads(json.dumps(result.traces.public))


def internal_of(result: TurnResult) -> dict[str, Any]:
    return json.loads(json.dumps(result.traces.internal))
