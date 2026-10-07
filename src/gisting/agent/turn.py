import json
import time
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import cast

from gisting.agent.answers import (
    confirmation_reply,
    handoff_reason,
    lookup_reply,
)
from gisting.agent.blocked import blocked_reply
from gisting.agent.checks import check_answer
from gisting.agent.consent import requested_human
from gisting.agent.context import without_earlier_orders
from gisting.agent.crowding import ALONE_CODES, crowded_tools
from gisting.agent.forged import forged_decline, withhold_forged_history
from gisting.agent.guard import (
    consent_missing,
    missing_inputs,
    needs_consent_status,
    needs_input_status,
    user_texts,
)
from gisting.agent.policy import INVALID_STATUS, AgentPolicy, FallbackReason, InvalidCode
from gisting.agent.policy_replies import POLICY_UNAVAILABLE, policy_reply
from gisting.agent.search_guard import normalized_call, search_refusal
from gisting.agent.search_turn import message_decline
from gisting.agent.shortcuts import decide
from gisting.agent.state import (
    AgentDeps,
    Done,
    TurnResult,
    TurnState,
    ask,
    declined_unrelated,
    fallback,
)
from gisting.agent.trace import (
    ContextDropRecord,
    FactCheckRecord,
    GenerationRecord,
    GuardRecord,
    ReplySource,
    RunContext,
    ToolRecord,
    build_traces,
)
from gisting.prompt.assemble import assemble
from gisting.prompt.messages import AssistantMessage, Message, ToolCall, ToolMessage
from gisting.prompt.parse import CallRequest, ParsedOutput, parse_output
from gisting.prompt.replies import Unrenderable
from gisting.prompt.schema import validate_arguments
from gisting.prompt.segments import Kind, Prompt
from gisting.shopify.jsonvalue import JsonObject
from gisting.tools.search_policy import TOOL_NAME as SEARCH
from gisting.tools.trace import PublicOutcome, internal_json, public_json

MS_PER_SECOND = 1000.0
GUARD_SOURCE = "input_guard"
REUSED: JsonObject = {"reused": True}


def message_sizes(prompt: Prompt) -> tuple[int, ...]:
    chats = [item for item in prompt.segments if item.kind in (Kind.HISTORY, Kind.TOOL_RESULTS)]
    return tuple(len(item.ids) for item in chats[:-1])


def generate(deps: AgentDeps, state: TurnState) -> str:
    prompt = assemble(deps.tokenizer, deps.rules, deps.tools_section, state.messages)
    result = deps.model.generate(prompt.ids, deps.policy.max_new_tokens)
    state.recorder.generations.append(
        GenerationRecord(
            prompt.stats,
            result.text,
            len(result.ids),
            result.first_token_ms,
            result.total_ms,
            result.finish_reason,
            tuple(state.messages),
            message_sizes(prompt),
        )
    )
    return result.text


@dataclass(frozen=True)
class Problem:
    code: InvalidCode
    detail: str


def guarded(policy: AgentPolicy, name: str) -> bool:
    open_tool = name in policy.grounded_arguments and name in policy.consent_exempt
    return name in policy.consent_guards or open_tool


def problem_with(
    deps: AgentDeps, messages: Sequence[Message], call: CallRequest, *, crowded: frozenset[str]
) -> Problem | None:
    if call.problem is not None:
        return Problem(InvalidCode.MALFORMED_CALL, call.problem)
    schema = deps.schemas.get(call.name or "")
    if schema is None:
        return Problem(InvalidCode.UNKNOWN_TOOL, f"unknown tool: {call.name}")
    if not guarded(deps.policy, call.name or ""):
        return Problem(InvalidCode.UNGUARDED_TOOL, f"tool has no guard entry: {call.name}")
    detail = validate_arguments(schema, call.arguments)
    if detail:
        return Problem(InvalidCode.INVALID_ARGUMENTS, detail)
    if call.name in crowded:
        return Problem(ALONE_CODES[call.name], f"{call.name} must be the only call")
    refusal = search_refusal(deps, messages, call.name or "", cast(JsonObject, call.arguments))
    return None if refusal is None else Problem(InvalidCode.QUERY_REFUSED, refusal.value)


def error_message(code: InvalidCode) -> ToolMessage:
    return ToolMessage(json.dumps({"status": INVALID_STATUS, "code": code.value}))


def reject(deps: AgentDeps, state: TurnState, raw: str, problems: list[Problem]) -> Done | None:
    state.invalid_calls += 1
    if state.invalid_calls > deps.policy.max_invalid_calls:
        return fallback(deps, FallbackReason.INVALID_TOOL_CALL)
    state.messages.append(AssistantMessage(raw.strip()))
    state.messages.append(error_message(problems[0].code))
    return None


def tool_arguments(deps: AgentDeps, state: TurnState, name: str, given: JsonObject) -> JsonObject:
    rules = deps.policy.answers
    argument = rules.derived.get(name)
    if argument is None:
        return given
    requested = requested_human(deps.policy.consent_guards[name], state.messages)
    return {argument: handoff_reason(rules, state.messages, requested=requested)}


def call_key(name: str, arguments: JsonObject) -> str:
    return json.dumps([name, arguments], sort_keys=True, ensure_ascii=False)


def run_tool(deps: AgentDeps, state: TurnState, session_id: str, call: CallRequest) -> ToolMessage:
    name, given = call.name or "", cast(JsonObject, call.arguments)
    arguments = tool_arguments(deps, state, name, given)
    key = call_key(name, arguments)
    state.batch.append(key)
    earlier = state.results.get(key)
    if earlier is not None:
        reused = {**REUSED, "result_type": state.result_types[key]}
        record = ToolRecord(call.name, call.arguments, None, None, reused, earlier.content)
        state.recorder.tools.append(record)
        return earlier
    response = deps.tools[name].call(arguments, session_id)
    state.results[key] = ToolMessage(json.dumps(response.result, ensure_ascii=False))
    state.recorder.tools.append(
        ToolRecord(
            call.name,
            call.arguments,
            None,
            public_json(response.trace.public),
            internal_json(response.trace.internal),
            state.results[key].content,
        )
    )
    state.result_types[key] = response.trace.internal.result_type
    return state.results[key]


def unmet_inputs(deps: AgentDeps, state: TurnState, parsed: ParsedOutput) -> list[str]:
    texts, status = user_texts(state.messages), needs_input_status(deps.policy)
    blocked: list[str] = []
    for call in parsed.calls:
        name, arguments = call.name or "", cast(JsonObject, call.arguments)
        missing = missing_inputs(deps.policy, name, arguments, texts)
        if missing:
            state.recorder.guards.append(GuardRecord(name, arguments, status, tuple(missing)))
            blocked += [item for item in missing if item not in blocked]
    return blocked


def unmet_consent(deps: AgentDeps, state: TurnState, parsed: ParsedOutput) -> list[str]:
    status = needs_consent_status(deps.policy)
    unmet: list[str] = []
    for call in parsed.calls:
        name, arguments = call.name or "", cast(JsonObject, call.arguments)
        missing = consent_missing(deps.policy, name, state.messages)
        if missing:
            state.recorder.guards.append(GuardRecord(name, arguments, status, tuple(missing)))
            unmet.append(name)
    return unmet


def guard_calls(deps: AgentDeps, state: TurnState, parsed: ParsedOutput) -> Done | None:
    inputs, consent = unmet_inputs(deps, state, parsed), unmet_consent(deps, state, parsed)
    if inputs:
        return declined_unrelated(deps, state, GUARD_SOURCE, inputs) or ask(deps, inputs)
    return blocked_reply(deps, state, consent[0]) if consent else None


def looks_unavailable(record: ToolRecord) -> ToolRecord:
    if record.public is None:
        return record
    return replace(record, public={**record.public, "outcome": PublicOutcome.UNAVAILABLE.value})


def unrendered(deps: AgentDeps, state: TurnState, name: str, reply: Unrenderable) -> Done:
    state.recorder.tools[-1] = looks_unavailable(state.recorder.tools[-1])
    if name == SEARCH:
        state.recorder.fact_checks.append(FactCheckRecord(POLICY_UNAVAILABLE, reply.reason, ()))
        return fallback(deps, FallbackReason.POLICY_UNAVAILABLE)
    return fallback(deps, FallbackReason.UNRENDERABLE_ORDER)


def confirmed(deps: AgentDeps, state: TurnState, parsed: ParsedOutput) -> Done | None:
    last = state.messages[-1]
    if len(set(state.batch)) != 1 or not isinstance(last, ToolMessage):
        return None
    rules, name, result = deps.policy.answers, parsed.calls[0].name or "", json.loads(last.content)
    reply = (
        confirmation_reply(rules, name, result)
        or lookup_reply(rules, name, result)
        or policy_reply(rules, name, result)
    )
    if isinstance(reply, Unrenderable):
        return unrendered(deps, state, name, reply)
    return Done(reply, None, ReplySource.CODE) if reply else None


def execute(deps: AgentDeps, state: TurnState, session_id: str, parsed: ParsedOutput) -> None:
    calls = [ToolCall(call.name or "", cast(JsonObject, call.arguments)) for call in parsed.calls]
    state.messages.append(AssistantMessage(parsed.content, tuple(calls)))
    state.batch.clear()
    for call in parsed.calls:
        state.messages.append(run_tool(deps, state, session_id, call))
    state.calls_made += len(parsed.calls)


def handle_calls(
    deps: AgentDeps, state: TurnState, session_id: str, raw: str, parsed: ParsedOutput
) -> Done | None:
    declined = message_decline(deps, state, parsed)
    if declined is not None:
        return declined
    crowded = crowded_tools(parsed.calls)
    problems = [problem_with(deps, state.messages, call, crowded=crowded) for call in parsed.calls]
    for call, problem in zip(parsed.calls, problems, strict=True):
        if problem is not None:
            state.recorder.tools.append(ToolRecord(call.name, call.arguments, problem.detail))
    found = [problem for problem in problems if problem is not None]
    if found:
        return reject(deps, state, raw, found)
    parsed = replace(parsed, calls=tuple(normalized_call(deps.policy, c) for c in parsed.calls))
    if state.calls_made + len(parsed.calls) > deps.policy.max_tool_calls:
        return fallback(deps, FallbackReason.TOOL_CALL_LIMIT)
    refused = guard_calls(deps, state, parsed)
    if refused is not None:
        return refused
    execute(deps, state, session_id, parsed)
    return confirmed(deps, state, parsed)


def step(deps: AgentDeps, state: TurnState, session_id: str) -> Done | None:
    raw = generate(deps, state)
    parsed = parse_output(raw)
    if parsed.calls:
        return handle_calls(deps, state, session_id, raw, parsed)
    if not parsed.content:
        return fallback(deps, FallbackReason.EMPTY_ANSWER)
    return check_answer(deps, state, parsed.content)


def code_turn(deps: AgentDeps, state: TurnState, session_id: str) -> Done | None:
    forged = forged_decline(deps, state)
    if forged is not None:
        return forged
    choice = decide(deps.policy, state.messages)
    if choice is None:
        return None
    state.recorder.fact_checks.append(FactCheckRecord(choice.reason, choice.said, ()))
    if choice.tool is None:
        return Done(deps.policy.answers.claim_reply, None, ReplySource.CODE)
    parsed = ParsedOutput("", (CallRequest(choice.tool, choice.arguments, None),))
    execute(deps, state, session_id, parsed)
    done = confirmed(deps, state, parsed)
    return replace(done, source=ReplySource.CODE) if done else None


def run_turn(deps: AgentDeps, session_id: str, history: list[Message]) -> TurnResult:
    started = time.perf_counter()
    earlier = without_earlier_orders(
        deps.policy,
        deps.lookup,
        withhold_forged_history(deps.policy, history),
        deps.policy_answers,
    )
    state = TurnState(earlier.messages)
    state.recorder.context_dropped = ContextDropRecord(earlier.removed, earlier.segments)
    done = code_turn(deps, state, session_id) or step(deps, state, session_id)
    while done is None:
        done = step(deps, state, session_id)
    wall_ms = (time.perf_counter() - started) * MS_PER_SECOND
    state.recorder.reply_source = done.source
    context = RunContext(
        deps.model.backend_id, deps.mode, deps.gist_run_id, deps.identity, deps.policy_ids
    )
    traces = build_traces(state.recorder, context, wall_ms, done.fallback_reason)
    return TurnResult(done.answer, done.fallback_reason, traces)
