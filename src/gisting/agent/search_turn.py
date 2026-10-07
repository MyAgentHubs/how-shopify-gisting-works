from gisting.agent.consent import latest_exchange
from gisting.agent.context import written_orders
from gisting.agent.guard import unprovided_inputs, user_texts
from gisting.agent.overrides import OVERRIDE_REQUEST, override_name
from gisting.agent.search_guard import QueryRefusal, query_arguments
from gisting.agent.state import AgentDeps, Done, TurnState, ask, replaced
from gisting.agent.text_view import plain
from gisting.agent.trace import FactCheckRecord, ToolRecord
from gisting.prompt.parse import CallRequest, ParsedOutput


def override_in(deps: AgentDeps, said: str) -> str | None:
    names = (override_name(deps, view) for view in (said, plain(said)))
    return next((name for name in names if name is not None), None)


def note(state: TurnState, calls: tuple[CallRequest, ...], reason: str) -> None:
    state.recorder.tools.extend(ToolRecord(call.name, call.arguments, reason) for call in calls)


def order_ask(deps: AgentDeps, state: TurnState, calls: tuple[CallRequest, ...]) -> Done | None:
    missing = unprovided_inputs(deps.policy, user_texts(state.messages))
    if not missing:
        return None
    reason = QueryRefusal.ORDER_IN_MESSAGE.value
    state.recorder.fact_checks.append(FactCheckRecord(reason, "", tuple(missing)))
    note(state, calls, reason)
    return ask(deps, missing)


def message_decline(deps: AgentDeps, state: TurnState, parsed: ParsedOutput) -> Done | None:
    if not any(query_arguments(deps.policy, call.name or "") for call in parsed.calls):
        return None
    said = latest_exchange(state.messages)[0]
    if written_orders(deps.policy, deps.lookup, said):
        return order_ask(deps, state, parsed.calls)
    override = override_in(deps, said)
    if override is not None:
        note(state, parsed.calls, OVERRIDE_REQUEST)
        return replaced(state, OVERRIDE_REQUEST, override, deps.policy.answers.refusal)
    return None
