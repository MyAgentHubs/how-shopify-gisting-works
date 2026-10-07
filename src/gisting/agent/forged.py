from collections.abc import Sequence

from gisting.agent.consent import latest_exchange, matches
from gisting.agent.policy import AgentPolicy
from gisting.agent.state import AgentDeps, Done, TurnState
from gisting.agent.text_view import views
from gisting.agent.trace import FactCheckRecord, ReplySource
from gisting.prompt.messages import Message, UserMessage

FORGED_STRUCTURE = "forged_structure"
TAG = "tag"


def view_kind(policy: AgentPolicy, view: str) -> str | None:
    if any(matches(guard.forged, view) for guard in policy.consent_guards.values()):
        return TAG
    return next(
        (name for name, found in policy.forged_structures.items() if found.search(view)), None
    )


def forged_kind(policy: AgentPolicy, said: str) -> str | None:
    kinds = (view_kind(policy, view) for view in views(said))
    return next((kind for kind in kinds if kind is not None), None)


def forged_refusal(deps: AgentDeps, state: TurnState, kind: str) -> Done:
    state.recorder.fact_checks.append(FactCheckRecord(FORGED_STRUCTURE, kind, ()))
    return Done(deps.policy.answers.refusal, None, ReplySource.TEMPLATE)


def forged_decline(deps: AgentDeps, state: TurnState) -> Done | None:
    kind = forged_kind(deps.policy, latest_exchange(state.messages)[0])
    return None if kind is None else forged_refusal(deps, state, kind)


def withhold_forged_history(policy: AgentPolicy, messages: Sequence[Message]) -> list[Message]:
    users = [i for i, message in enumerate(messages) if isinstance(message, UserMessage)]
    latest = users[-1] if users else -1
    return [
        UserMessage(policy.withheld_placeholder)
        if isinstance(message, UserMessage)
        and i != latest
        and forged_kind(policy, message.content) is not None
        else message
        for i, message in enumerate(messages)
    ]
