from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from gisting.shopify.apply_order import describe
from gisting.shopify.assess import Step, assess, email_status
from gisting.shopify.client import AdminClient
from gisting.shopify.demo_email import demo_email
from gisting.shopify.order_state import OrderState
from gisting.shopify.plan import PlanEntry, ShipmentPlan
from gisting.shopify.results import NotExecuted
from gisting.shopify.run_plan import Pacing, paced

EXAMPLE_COUNT = 5
STEP_LABELS = {
    Step.UPDATE_ORDER: "写入邮箱与备注",
    Step.CREATE_FULFILLMENT: "创建发货(不通知客户)",
    Step.CREATE_EVENT: "写入物流事件",
    Step.ADD_TAG: "加标签",
}


@dataclass(frozen=True)
class Row:
    entry: PlanEntry
    current: str
    actions: tuple[str, ...]
    problem: str | None
    skipped: bool = False
    email: str | None = None


def action_labels(steps: Sequence[Step], entry: PlanEntry, plan: ShipmentPlan) -> tuple[str, ...]:
    labels: list[str] = []
    for step in steps:
        label = STEP_LABELS[step]
        if step is Step.CREATE_EVENT and entry.event is not None:
            label = f"{label} {entry.event.status}"
        if step is Step.ADD_TAG:
            label = f"{label} {plan.plan_tag}"
        labels.append(label)
    return tuple(labels)


def inspect_order(
    client: AdminClient, plan: ShipmentPlan, entry: PlanEntry, state: OrderState, secret: str
) -> Row:
    expected = demo_email(secret, entry.order)
    email = email_status(state, expected)
    refusal = client.writable(state)
    if isinstance(refusal, NotExecuted):
        return Row(entry, state.status, (), f"拒绝写入: {refusal.cause.value}", email=email)
    assessment = assess(state, entry, plan, expected)
    if assessment.skip:
        return Row(entry, state.status, (), None, skipped=True, email=email)
    actions = action_labels(assessment.steps, entry, plan)
    return Row(entry, state.status, actions, assessment.diverged, email=email)


def dry_run(
    client: AdminClient,
    plan: ShipmentPlan,
    entries: Sequence[PlanEntry],
    pacing: Pacing,
    secret: str,
) -> list[Row]:
    rows: list[Row] = []
    for entry in paced(entries, pacing):
        state = client.fetch_order(entry.order)
        if isinstance(state, OrderState):
            rows.append(inspect_order(client, plan, entry, state, secret))
        else:
            rows.append(Row(entry, "?", (), f"无法核对: {describe(state)}"))
    return rows


def describe_row(row: Row) -> str:
    email = f" [email: {row.email}]" if row.email else ""
    plan_text = f"{row.entry.order} {row.entry.scenario} (现状 {row.current}){email}"
    if row.problem:
        return f"{plan_text}: {row.problem}"
    if row.skipped:
        return f"{plan_text}: 已带标签，将跳过"
    return f"{plan_text}: " + " -> ".join(row.actions)


def render_report(rows: Sequence[Row], plan_size: int) -> str:
    scenarios = Counter(row.entry.scenario for row in rows)
    problems = [row for row in rows if row.problem]
    unverified = [row for row in problems if row.current == "?"]
    skipped = [row for row in rows if row.skipped]
    ready = len(rows) - len(problems) - len(skipped)
    lines = [
        "dry-run（只读，未调用任何 mutation）",
        f"核对订单 {len(rows)} / 计划 {plan_size}",
        "场景分布（本次核对）:",
        *(f"  {name} {count}" for name, count in sorted(scenarios.items())),
        f"可按计划执行 {ready}，已带标签将跳过 {len(skipped)}，"
        f"与现状有差异 {len(problems) - len(unverified)}，无法核对 {len(unverified)}",
        f"示例（前 {EXAMPLE_COUNT} 单的计划动作）:",
        *(f"  {describe_row(row)}" for row in rows[:EXAMPLE_COUNT]),
    ]
    if problems:
        lines.append("差异:")
        lines.extend(f"  {describe_row(row)}" for row in problems)
    return "\n".join(lines) + "\n"
