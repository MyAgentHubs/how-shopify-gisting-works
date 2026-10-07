from gisting.agent.checks import refusal_ask
from gisting.agent.consent import (
    customer_words,
    latest_exchange,
    mentioned_request,
    offered,
    requested_human,
)
from gisting.agent.guard import user_texts
from gisting.agent.policy import Grounding
from gisting.agent.shortcuts import numbers_written, order_as_written
from gisting.agent.state import AgentDeps, Done, TurnState, need_consent
from gisting.agent.trace import FactCheckRecord, ReplySource
from gisting.prompt.messages import UserMessage

NO_OFFER_CONTEXT = "blocked_tool_no_offer_context"
DETAILS_GIVEN = "details_given"


def offer_context(deps: AgentDeps, state: TurnState, tool: str) -> bool:
    guard = deps.policy.consent_guards[tool]
    previous = latest_exchange(state.messages)[1]
    if requested_human(guard, state.messages) or mentioned_request(guard, state.messages):
        return True
    if previous is None or not offered(guard, previous):
        return False
    return tool not in deps.policy.grounded_arguments or bool(
        order_as_written(deps.policy, state.messages)
    )


def details_given(deps: AgentDeps, state: TurnState, tool: str) -> bool:
    said = customer_words(deps.policy.consent_guards[tool], latest_exchange(state.messages)[0])
    return bool(deps.policy.patterns[Grounding.EMAIL].search(said)) and bool(
        numbers_written(deps.policy, UserMessage(said))
    )


def declined_or_asked(deps: AgentDeps, state: TurnState) -> Done:
    refusal = deps.policy.answers.refusal
    return refusal_ask(deps, state, refusal) or Done(refusal, None, ReplySource.TEMPLATE)


def blocked_reply(deps: AgentDeps, state: TurnState, tool: str) -> Done:
    if offer_context(deps, state, tool):
        return need_consent(deps, tool)
    ungrounded = tool not in deps.policy.grounded_arguments
    given = ungrounded and details_given(deps, state, tool)
    matched = f"{tool}:{DETAILS_GIVEN}" if given else tool
    state.recorder.fact_checks.append(FactCheckRecord(NO_OFFER_CONTEXT, matched, ()))
    later_handoff = ungrounded and len(user_texts(state.messages)) > 1
    return need_consent(deps, tool) if given or later_handoff else declined_or_asked(deps, state)
