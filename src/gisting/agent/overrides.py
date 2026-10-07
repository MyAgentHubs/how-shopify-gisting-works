from gisting.agent.conclusions import APOSTROPHES
from gisting.agent.consent import latest_exchange
from gisting.agent.guard import asks_for_own_order
from gisting.agent.state import AgentDeps, Done, TurnState, replaced
from gisting.agent.text_view import views

OVERRIDE_REQUEST = "override_request"


def override_name(deps: AgentDeps, said: str) -> str | None:
    plains = [view.translate(APOSTROPHES) for view in views(said)]
    patterns = deps.policy.override_requests
    return next(
        (name for name, found in patterns.items() if any(found.search(plain) for plain in plains)),
        None,
    )


def override_refusal(deps: AgentDeps, state: TurnState, content: str) -> Done | None:
    rules = deps.policy.answers
    said, previous = latest_exchange(state.messages)
    if content.strip() == rules.refusal:
        return None
    name = override_name(deps, said)
    if name is None:
        return None
    if name not in deps.policy.override_unconditional and asks_for_own_order(
        deps.policy, said, previous
    ):
        return None
    return replaced(state, OVERRIDE_REQUEST, name, rules.refusal)
