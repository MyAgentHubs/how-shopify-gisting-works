from fakes.tokenizer import synthetic_prompt_tokenizer
from prompt_support import FOUND, LOOKUP, build, tools

from gisting.prompt.assemble import Rules
from gisting.prompt.messages import AssistantMessage, ToolMessage, UserMessage
from gisting.prompt.segments import Kind, PromptStats, total_stats

GIST_IDS = (11, 12, 13)


def test_segments_sum_to_the_total() -> None:
    prompt = build(synthetic_prompt_tokenizer(), [*LOOKUP, ToolMessage(FOUND)])
    stats = prompt.stats
    assert stats.rules + stats.tools + stats.history + stats.tool_results == stats.total
    assert stats.total == len(prompt.ids)
    assert min(stats.rules, stats.tools, stats.history, stats.tool_results) > 0


def test_tool_messages_count_as_tool_results_and_the_rest_as_history() -> None:
    tokenizer = synthetic_prompt_tokenizer()
    without = build(tokenizer, LOOKUP).stats
    with_result = build(tokenizer, [*LOOKUP, ToolMessage(FOUND)]).stats
    assert without.tool_results == 0
    assert with_result.tool_results > 0
    assert with_result.history == without.history
    assert (with_result.rules, with_result.tools) == (without.rules, without.tools)


def test_stats_grow_with_history_only() -> None:
    tokenizer = synthetic_prompt_tokenizer()
    short = build(tokenizer, [UserMessage("hi")]).stats
    long = build(tokenizer, [UserMessage("hi"), AssistantMessage("hello"), UserMessage("more")])
    assert long.stats.history > short.history
    assert (long.stats.rules, long.stats.tools) == (short.rules, short.tools)


def test_rules_segment_is_replaceable_and_nothing_else_changes() -> None:
    tokenizer = synthetic_prompt_tokenizer()
    full = build(tokenizer, LOOKUP)
    gist = build(tokenizer, LOOKUP, rules=Rules(GIST_IDS))
    assert [s.ids for s in gist.segments[1:]] == [s.ids for s in full.segments[1:]]
    assert gist.segments[0].kind is Kind.RULES
    assert gist.segments[0].ids[-len(GIST_IDS) :] == GIST_IDS
    assert gist.stats.rules < full.stats.rules
    assert gist.stats.tools == full.stats.tools == len(tools(tokenizer).ids)


def test_total_stats_adds_every_field() -> None:
    first, second = PromptStats(1, 2, 3, 4, 10), PromptStats(5, 6, 7, 8, 26)
    assert total_stats([first, second]) == PromptStats(6, 8, 10, 12, 36)
    assert first.as_json()["total"] == 10
