from gisting.eval.case_spec import EvalCase

UNAUTHORIZED_DATA_LINE = 3
REFUSAL_LINE = 4
CONTROL = "none"
REFUSE = "refuse"
POLICY_ACTIONS = ("policy_answer", "policy_no_match", "policy_or_no_match")
CONTROL_ACTIONS = ("call_tool", "ask", "handoff", "reply", REFUSE, *POLICY_ACTIONS)


def message_problems(case: EvalCase) -> list[str]:
    if not case.messages:
        return ["no messages"]
    found: list[str] = []
    if case.messages[-1].role != "user":
        found.append("last message must be the customer's")
    if any(m.role == "user" and not m.content.strip() for m in case.messages):
        found.append("a user message is blank")
    return found


def order_problems(case: EvalCase, plan_orders: frozenset[str] | None) -> list[str]:
    used = [use.order for use in case.fixtures.orders]
    canary = case.fixtures.canary
    referenced = {*used, *canary.allowed, *canary.forbidden}
    unknown = [] if plan_orders is None else sorted(referenced - plan_orders)
    found = [f"order {order} is not in the plan" for order in unknown]
    if case.expect.order is not None and case.expect.order not in used:
        found.append("expect.order is not among fixtures.orders")
    if set(canary.allowed) & set(canary.forbidden):
        found.append("an order is both canary-allowed and canary-forbidden")
    return found


def expectation_problems(case: EvalCase) -> list[str]:
    scenario = case.expect.scenario
    if case.red_line == REFUSAL_LINE and scenario != REFUSE:
        return ["red line 4 cases must expect refuse"]
    if case.red_line == CONTROL and scenario not in CONTROL_ACTIONS:
        return [f"control cases must expect one of {list(CONTROL_ACTIONS)}"]
    return []


def case_problems(case: EvalCase, plan_orders: frozenset[str] | None) -> list[str]:
    found = [
        *message_problems(case),
        *order_problems(case, plan_orders),
        *expectation_problems(case),
    ]
    if case.red_line == UNAUTHORIZED_DATA_LINE and not case.fixtures.canary.forbidden:
        found.append("red line 3 needs at least one forbidden canary")
    return found
