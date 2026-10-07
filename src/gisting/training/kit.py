from collections.abc import Sequence
from dataclasses import dataclass

from gisting.agent.policy import load_agent_policy
from gisting.prompt.assemble import Rules, assemble, full_rules, gist_rules, tools_segment
from gisting.prompt.messages import Message
from gisting.prompt.schema import load_tool_schemas
from gisting.prompt.segments import Prompt, Segment
from gisting.prompt.tokenizer import PromptTokenizer


@dataclass(frozen=True)
class Kit:
    tokenizer: PromptTokenizer
    tools: Segment
    full: Rules
    gist: Rules | None
    max_new_tokens: int

    def prompt(self, messages: Sequence[Message], *, gist: bool) -> Prompt:
        rules = self.gist if gist else self.full
        if rules is None:
            message = "this kit was made without gist rules"
            raise ValueError(message)
        return assemble(self.tokenizer, rules, self.tools, messages)


def make_kit(tokenizer: PromptTokenizer, k: int | None = None) -> Kit:
    tools = tools_segment(tokenizer, load_tool_schemas().values())
    policy = load_agent_policy()
    gist = None if k is None else gist_rules(tokenizer, k)
    return Kit(tokenizer, tools, full_rules(tokenizer), gist, policy.max_new_tokens)
