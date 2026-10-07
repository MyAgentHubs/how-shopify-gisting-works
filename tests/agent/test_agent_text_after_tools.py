from dataclasses import dataclass, replace

import pytest
from agent_support import internal_of, rig, tool_call

from gisting.agent.policy import FallbackReason, load_agent_policy
from gisting.agent.state import ToolRunner
from gisting.prompt.messages import UserMessage
from gisting.shopify.jsonvalue import JsonObject
from gisting.tools.handoff import HandoffToHuman
from gisting.tools.lookup_order import ToolResponse

POLICY = load_agent_policy()
MESSAGE = (
    "Where is order #1042? I want to talk to a human and please send a reminder to ship my order"
)
HANDOFF = tool_call("handoff_to_human")
CONCLUSIONS = [
    "Your order will arrive on Tuesday, October 6 with FedEx, tracking FX1234567890.",
    "Your order #1042 is delayed and belongs to John Smith.",
]


@dataclass
class Ticketless:
    inner: ToolRunner

    def call(self, arguments: JsonObject, session_id: str) -> ToolResponse:
        response = self.inner.call(arguments, session_id)
        return replace(response, result={"status": response.result["status"]})


@pytest.mark.parametrize("text", CONCLUSIONS)
def test_text_written_after_tools_that_ran_still_goes_through_the_fact_net(text: str) -> None:
    subject = rig(HANDOFF, text, max_tool_calls=2)
    subject.handoff.inner = Ticketless(HandoffToHuman())
    result = subject.run([UserMessage(MESSAGE)])
    assert result.answer != text
    assert result.fallback_reason is FallbackReason.UNCHECKED_CONCLUSION or (
        internal_of(result)["reply_source"] in {"template", "fallback"}
    )
    assert "FedEx" not in result.answer
    assert "John Smith" not in result.answer
