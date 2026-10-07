import json
from pathlib import Path

import pytest
from agent_support import good_call, tool_call

from gisting.agent.policy import AgentPolicyError, FallbackReason, load_agent_policy
from gisting.prompt.parse import parse_output


def test_plain_text_has_no_calls() -> None:
    parsed = parse_output("  Sorry, I only handle orders.  ")
    assert parsed.content == "Sorry, I only handle orders."
    assert parsed.calls == ()


def test_a_call_block_is_parsed_and_removed_from_the_content() -> None:
    parsed = parse_output(f"Checking. {tool_call(order_number='#1042', email='a@b.c')}")
    assert parsed.content == "Checking."
    assert len(parsed.calls) == 1
    assert parsed.calls[0].name == "lookup_order"
    assert parsed.calls[0].arguments == {"order_number": "#1042", "email": "a@b.c"}
    assert parsed.calls[0].problem is None


def test_two_blocks_give_two_calls() -> None:
    assert len(parse_output(good_call() + "\n" + good_call()).calls) == 2


@pytest.mark.parametrize(
    "text",
    [
        "<tool_call>\nnot json\n</tool_call>",
        "<tool_call>\n[1]\n</tool_call>",
        '<tool_call>\n{"name": 3, "arguments": {}}\n</tool_call>',
        '<tool_call>\n{"name": "lookup_order"}\n</tool_call>',
        '<tool_call>\n{"name": "lookup_order", "arguments": {"a": ',
    ],
)
def test_broken_calls_carry_a_problem(text: str) -> None:
    calls = parse_output(text).calls
    assert len(calls) == 1
    assert calls[0].problem is not None
    assert calls[0].name is None


def test_text_before_an_unterminated_call_is_kept() -> None:
    parsed = parse_output(f"Hold on. <tool_call>\n{json.dumps({'name': 'x'})[:8]}")
    assert parsed.content == "Hold on."
    assert parsed.calls[0].problem == "tool call is incomplete"


def test_arguments_may_be_any_json_so_the_schema_can_judge_them() -> None:
    call = parse_output(tool_call(order_number=5)).calls[0]
    assert call.problem is None
    assert call.arguments == {"order_number": 5}


def test_repo_policy_loads_with_a_reply_for_every_fallback_reason() -> None:
    policy = load_agent_policy()
    assert policy.max_tool_calls == 2
    assert set(policy.fallback_replies) == set(FallbackReason)
    assert all(policy.fallback_replies.values())


@pytest.mark.parametrize(
    "text",
    [
        "{",
        "[]",
        "{}",
        '{"max_tool_calls_per_turn": 0}',
    ],
)
def test_malformed_policy_is_rejected(tmp_path: Path, text: str) -> None:
    path = tmp_path / "policy.json"
    path.write_text(text)
    with pytest.raises(AgentPolicyError):
        load_agent_policy(path)


def test_missing_policy_file_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(AgentPolicyError):
        load_agent_policy(tmp_path / "absent.json")


def test_policy_with_a_missing_reply_is_rejected(tmp_path: Path) -> None:
    document = json.loads(
        (Path(__file__).resolve().parents[2] / "prompts" / "agent_policy.json").read_text()
    )
    del document["fallback_replies"]["empty_answer"]
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(document))
    with pytest.raises(AgentPolicyError):
        load_agent_policy(path)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("grounded_arguments", {"lookup_order": {"email": "fuzzy"}}),
        ("grounded_arguments", {"lookup_order": "email"}),
        ("needs_input_result", {"status": "needs_customer_input"}),
        ("needs_consent_result", {"status": "needs_customer_consent"}),
        ("consent_guards", {"handoff_to_human": "yes"}),
        ("consent_guards", {"handoff_to_human": {}}),
        ("consent_exempt", "lookup_order"),
        ("patterns", {"email": "x"}),
        ("patterns", {"email": "(", "order_number": "(\\d+)"}),
        ("patterns", {"email": "x", "order_number": "\\d+"}),
        ("patterns", {"email": "x", "order_number": "(\\d+)", "extra": "y"}),
    ],
)
def test_policy_with_a_malformed_guard_section_is_rejected(
    tmp_path: Path, key: str, value: object
) -> None:
    document = json.loads(
        (Path(__file__).resolve().parents[2] / "prompts" / "agent_policy.json").read_text()
    )
    document[key] = value
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(document))
    with pytest.raises(AgentPolicyError):
        load_agent_policy(path)
