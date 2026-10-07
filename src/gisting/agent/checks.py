from gisting.agent.answers import (
    false_claim,
    false_promise,
    probes_rules,
    refusal_intent,
)
from gisting.agent.conclusions import find_conclusion
from gisting.agent.consent import latest_exchange, looks_like_ask
from gisting.agent.guard import (
    ask_reply,
    asks_for_own_order,
    unprovided_inputs,
    user_texts,
)
from gisting.agent.overrides import override_name, override_refusal
from gisting.agent.policy import AgentPolicy, FallbackReason
from gisting.agent.rules_echo import echoed_rules
from gisting.agent.state import (
    AgentDeps,
    Done,
    TurnState,
    ask,
    declined_unrelated,
    executed,
    fallback,
    replaced,
)
from gisting.agent.time_claims import UNSUPPORTED_TIME_CLAIM, unsupported_claims
from gisting.agent.trace import (
    FactCheckRecord,
    ReplySource,
)
from gisting.prompt.messages import AssistantMessage, Message, ToolMessage, UserMessage

MISDIRECTED_ASK = "misdirected_ask"
UNEXAMPLED_ASK = "ask_without_example"
REWORDED_ASK = "reworded_ask"
FALSE_CONFIRMATION = "false_confirmation"
PROMISE = "promise"
REFUSAL_ON_ORDER = "refusal_on_order_question"
REFUSAL_NORMALIZED = "refusal_normalized"
RULES_ECHO = "rules_echo"


def ask_kind(policy: AgentPolicy, said: str) -> str | None:
    if said in policy.needs_input_bare_replies.values():
        return UNEXAMPLED_ASK
    if said in policy.needs_input_replies.values():
        return MISDIRECTED_ASK
    return REWORDED_ASK if looks_like_ask(policy.ask_detection, said) else None


def corrected_ask(deps: AgentDeps, state: TurnState, content: str) -> Done:
    said, policy = content.strip(), deps.policy
    kind = ask_kind(policy, said)
    missing = unprovided_inputs(policy, user_texts(state.messages))
    if kind is None or not missing:
        return Done(content)
    unrelated = declined_unrelated(deps, state, kind, missing)
    if unrelated is not None:
        return unrelated
    if ask_reply(policy, missing) == said:
        return Done(content)
    state.recorder.fact_checks.append(FactCheckRecord(kind, said, tuple(missing)))
    return ask(deps, missing)


def refusal_ask(deps: AgentDeps, state: TurnState, content: str) -> Done | None:
    rules, texts = deps.policy.answers, user_texts(state.messages)
    missing = unprovided_inputs(deps.policy, texts)
    if content.strip() != rules.refusal or not missing or not texts:
        return None
    said, previous = latest_exchange(state.messages)
    if override_name(deps, said) is not None:
        return None
    if not asks_for_own_order(deps.policy, said, previous):
        return None
    state.recorder.fact_checks.append(FactCheckRecord(REFUSAL_ON_ORDER, said, tuple(missing)))
    return ask(deps, missing)


def refusing(deps: AgentDeps, state: TurnState, content: str) -> bool:
    rules = deps.policy.answers
    if len(user_texts(state.messages)) != 1 or content.strip() == rules.refusal:
        return False
    return refusal_intent(rules, content) and not looks_like_ask(deps.policy.ask_detection, content)


def ask_or_fallback(deps: AgentDeps, state: TurnState, reason: str, matched: str) -> Done:
    missing = unprovided_inputs(deps.policy, user_texts(state.messages))
    state.recorder.fact_checks.append(FactCheckRecord(reason, matched, tuple(missing)))
    if not missing:
        return fallback(deps, FallbackReason.UNCHECKED_CONCLUSION)
    return declined_unrelated(deps, state, reason, missing) or ask(deps, missing)


def turn_tool_texts(messages: list[Message]) -> list[str]:
    last_user = max((i for i, m in enumerate(messages) if isinstance(m, UserMessage)), default=-1)
    return [m.content for m in messages[last_user + 1 :] if isinstance(m, ToolMessage)]


def earlier_reply_texts(messages: list[Message]) -> list[str]:
    last_user = max((i for i, m in enumerate(messages) if isinstance(m, UserMessage)), default=-1)
    return [m.content for m in messages[:last_user] if isinstance(m, AssistantMessage)]


def vet_time_claims(deps: AgentDeps, state: TurnState, done: Done) -> Done:
    if done.source is not ReplySource.MODEL:
        return done
    policy = deps.policy
    sources = [
        *user_texts(state.messages),
        *turn_tool_texts(state.messages),
        *earlier_reply_texts(state.messages),
        *policy.needs_input_replies.values(),
        *policy.needs_input_bare_replies.values(),
    ]
    found = unsupported_claims(policy.time_rules, done.answer, sources)
    if not found:
        return done
    return ask_or_fallback(deps, state, UNSUPPORTED_TIME_CLAIM, found[0])


def check_without_tool(deps: AgentDeps, state: TurnState, content: str) -> Done:
    rules = deps.policy.answers
    promise = false_promise(rules, content)
    if promise:
        return replaced(state, PROMISE, promise, rules.claim_reply)
    said = content
    if refusing(deps, state, content):
        state.recorder.fact_checks.append(FactCheckRecord(REFUSAL_NORMALIZED, content, ()))
        said = rules.refusal
    refused = refusal_ask(deps, state, said)
    if refused is not None:
        return refused
    if said != content:
        return Done(said, None, ReplySource.TEMPLATE)
    found = find_conclusion(deps.policy.conclusions, content)
    if found is None:
        return corrected_ask(deps, state, content)
    return ask_or_fallback(deps, state, found.reason, found.matched)


def rules_echo_reply(deps: AgentDeps, state: TurnState, matched: str) -> Done:
    rules, (said, _) = deps.policy.answers, latest_exchange(state.messages)
    if probes_rules(rules, said) or override_name(deps, said) is not None:
        return replaced(state, RULES_ECHO, matched, rules.refusal)
    return ask_or_fallback(deps, state, RULES_ECHO, matched)


def check_answer(deps: AgentDeps, state: TurnState, content: str) -> Done:
    rules = deps.policy.answers
    echoed = echoed_rules(deps.policy.rules_echo, content, latest_exchange(state.messages)[0])
    if echoed is not None:
        return rules_echo_reply(deps, state, echoed)
    claim = false_claim(rules, content)
    if claim and not executed(state, set(rules.confirmations)):
        return replaced(state, FALSE_CONFIRMATION, claim, rules.claim_reply)
    overridden = override_refusal(deps, state, content)
    if overridden is not None:
        return overridden
    return vet_time_claims(deps, state, check_without_tool(deps, state, content))
