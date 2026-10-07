from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from gisting.shopify.apply_order import describe
from gisting.shopify.assess import email_status
from gisting.shopify.client import AdminClient
from gisting.shopify.demo_email import demo_email
from gisting.shopify.order_state import OrderState
from gisting.shopify.plan import PlanEntry
from gisting.shopify.results import NotExecuted
from gisting.shopify.run_plan import Pacing, paced

HEADER = "dry-run（只读，未调用任何 mutation）"
VERDICT_LABELS = {
    "will_change": "将改",
    "matched": "已匹配",
    "refused": "被拒",
    "unreadable": "无法核对",
}


class Verdict(StrEnum):
    WILL_CHANGE = "will_change"
    MATCHED = "matched"
    REFUSED = "refused"
    UNREADABLE = "unreadable"


@dataclass(frozen=True)
class EmailRow:
    order: str
    verdict: Verdict
    detail: str = ""


def inspect_email(client: AdminClient, entry: PlanEntry, secret: str) -> EmailRow:
    state = client.fetch_order(entry.order)
    if not isinstance(state, OrderState):
        verdict = Verdict.REFUSED if isinstance(state, NotExecuted) else Verdict.UNREADABLE
        return EmailRow(entry.order, verdict, describe(state))
    refusal = client.writable(state)
    if isinstance(refusal, NotExecuted):
        return EmailRow(entry.order, Verdict.REFUSED, refusal.cause.value)
    if email_status(state, demo_email(secret, entry.order)) == "matches":
        return EmailRow(entry.order, Verdict.MATCHED)
    return EmailRow(entry.order, Verdict.WILL_CHANGE)


def dry_run_emails(
    client: AdminClient, entries: Sequence[PlanEntry], pacing: Pacing, secret: str
) -> list[EmailRow]:
    return [inspect_email(client, entry, secret) for entry in paced(entries, pacing)]


def render_email_report(rows: Sequence[EmailRow], plan_size: int) -> str:
    counts = Counter(row.verdict for row in rows)
    summary = "，".join(
        f"{VERDICT_LABELS[verdict.value]} {counts[verdict]}"
        for verdict in (Verdict.WILL_CHANGE, Verdict.MATCHED, Verdict.REFUSED, Verdict.UNREADABLE)
    )
    lines = [HEADER, f"订单 {len(rows)} / 计划 {plan_size}，{summary}"]
    lines.extend(
        f"  {row.order}: {VERDICT_LABELS[row.verdict.value]}: {row.detail}"
        for row in rows
        if row.verdict in (Verdict.REFUSED, Verdict.UNREADABLE)
    )
    return "\n".join(lines) + "\n"
