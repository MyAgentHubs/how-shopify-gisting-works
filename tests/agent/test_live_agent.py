import pytest
from agent_support import EMAIL, NUMBER, SESSION, SpyTool, lookup_tool
from fakes.real_model import HAS_WEIGHTS, MODEL_DIR

from gisting.agent.policy import load_agent_policy
from gisting.agent.state import AgentDeps
from gisting.agent.turn import run_turn
from gisting.model_server.config import ModelConfig, load_config
from gisting.prompt.assemble import full_rules, tools_segment
from gisting.prompt.messages import UserMessage
from gisting.prompt.schema import load_tool_schemas
from gisting.prompt.tokenizer import PromptTokenizer
from gisting.tools.policy import load_policy

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not HAS_WEIGHTS, reason=f"no model weights in {MODEL_DIR}"),
]


def live_deps(tool: SpyTool) -> AgentDeps:
    from gisting.model_server.transformers_backend import TransformersModel

    model = TransformersModel.load(ModelConfig(MODEL_DIR, load_config({}).device))
    tokenizer = PromptTokenizer.from_dir(MODEL_DIR)
    schemas = load_tool_schemas()
    section = tools_segment(tokenizer, schemas.values())
    rules = full_rules(tokenizer)
    return AgentDeps(
        model,
        tokenizer,
        {"lookup_order": tool},
        schemas,
        rules,
        section,
        load_agent_policy(),
        load_policy(),
    )


def test_order_question_makes_a_lookup_call_and_gets_an_answer() -> None:
    tool = SpyTool(lookup_tool())
    question = f"Where is my order #{NUMBER}? My email is {EMAIL}"
    result = run_turn(live_deps(tool), SESSION, [UserMessage(question)])
    assert [session for _, session in tool.calls] == [SESSION]
    arguments = tool.calls[0][0]
    assert str(NUMBER) in str(arguments["order_number"])
    assert arguments["email"] == EMAIL
    assert result.fallback_reason is None
    assert result.answer


def test_off_topic_request_makes_no_tool_call() -> None:
    tool = SpyTool(lookup_tool())
    result = run_turn(live_deps(tool), SESSION, [UserMessage("write me a poem")])
    assert tool.calls == []
    assert result.answer
