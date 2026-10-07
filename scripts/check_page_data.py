#!/usr/bin/env python3
import json
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import guardlib
from guardlib import Violation

from gisting.eval.web_pricing import load_pricing
from gisting.shopify.jsonvalue import Json, JsonObject
from gisting.shopify.order_name import InvalidOrderName, canonical_order_name
from gisting.shopify.plan import PlanFormatError, load_plan

PRICING = "apps/web/data/pricing.json"
EXAMPLES = "apps/web/data/example_orders.json"
PUBLIC_ORDERS = "apps/web/data/public_orders.json"
PUBLIC_ORDERS_PIN = "apps/web/data/public_orders_pin.json"
PUBLIC_ROW_COUNT = 8
RUNTIME = "apps/web/data/runtime.json"
PLAN = "data/demo-orders/shipment-plan-v1.json"
RELEASE_LOCK = "apps/web/data/release_lock.json"
ORDER_ROW_KEYS = frozenset({"id", "label_key", "order", "scenario", "email"})
HUMAN_ROW_KEYS = frozenset({"id", "label_key"})
LOCK_PATTERN_KEYS = ("email_shape", "sitekey_shape", "placeholder_email", "test_sitekey")
ROW_COUNT = 3
HUMAN_ROWS = 1
RUNTIME_KEYS = frozenset({"turnstile"})
TURNSTILE_KEYS = frozenset({"sitekey", "action"})
ACTION = re.compile(r"[a-z][a-z0-9-]{2,63}")


@dataclass(frozen=True)
class Placeholders:
    email_shape: re.Pattern[str]
    sitekey_shape: re.Pattern[str]
    email: re.Pattern[str]
    sitekey: re.Pattern[str]


@dataclass
class Findings:
    errors: list[Violation] = field(default_factory=list[Violation])
    pending: list[Violation] = field(default_factory=list[Violation])

    def error(self, path: str, reason: str) -> None:
        self.errors.append(Violation(path, 1, reason))

    def placeholder(self, path: str, reason: str) -> None:
        self.pending.append(Violation(path, 1, reason))


def read_object(root: Path, relative: str, found: Findings) -> JsonObject | None:
    try:
        document: Json = json.loads((root / relative).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        found.error(relative, f"cannot read the file as JSON: {error}")
        return None
    if not isinstance(document, dict):
        found.error(relative, "the file must hold a JSON object")
        return None
    return document


def read_placeholders(root: Path, found: Findings) -> Placeholders | None:
    document = read_object(root, RELEASE_LOCK, found)
    if document is None:
        return None
    try:
        patterns = [re.compile(str(document[key])) for key in LOCK_PATTERN_KEYS]
    except (KeyError, re.error) as error:
        found.error(RELEASE_LOCK, f"placeholder patterns are missing or invalid: {error!r}")
        return None
    return Placeholders(
        email_shape=patterns[0],
        sitekey_shape=patterns[1],
        email=patterns[2],
        sitekey=patterns[3],
    )


def check_pricing(root: Path, found: Findings) -> None:
    try:
        load_pricing(root / PRICING)
    except (OSError, ValueError) as error:
        found.error(PRICING, f"invalid pricing data: {error}")


def plan_scenarios(root: Path, found: Findings) -> dict[str, str]:
    try:
        plan = load_plan((root / PLAN).read_text(encoding="utf-8"))
    except (OSError, PlanFormatError) as error:
        found.error(PLAN, f"cannot read the shipment plan: {error}")
        return {}
    return {entry.order: entry.scenario for entry in plan.entries}


def canonical_or_none(raw: Json) -> str | None:
    try:
        return canonical_order_name(raw) if isinstance(raw, str) else None
    except InvalidOrderName:
        return None


def check_order_row(
    row: JsonObject,
    scenarios: dict[str, str],
    placeholders: Placeholders,
    found: Findings,
    path: str = EXAMPLES,
) -> None:
    order = canonical_or_none(row.get("order"))
    if order is None or order not in scenarios:
        found.error(path, f"order {row.get('order')!r} is not in the shipment plan")
        return
    if row.get("scenario") != scenarios[order]:
        found.error(path, f"{order} is {scenarios[order]} in the plan, not {row.get('scenario')!r}")
    label = row.get("label_key")
    if not isinstance(label, str) or label.rsplit(".", 1)[-1] != scenarios[order].lower():
        found.error(path, f"the label key of {order} does not name {scenarios[order]}")
    email = row.get("email")
    if not isinstance(email, str) or placeholders.email_shape.fullmatch(email) is None:
        found.error(path, f"the email of {order} is not a demo email address")
    elif placeholders.email.search(email):
        found.placeholder(path, f"the email of {order} is still the placeholder")


def example_rows(document: JsonObject | None, found: Findings) -> list[JsonObject]:
    if document is None:
        return []
    rows = document.get("examples")
    if not isinstance(rows, list) or len(rows) != ROW_COUNT:
        found.error(EXAMPLES, f"examples must be a list of {ROW_COUNT} rows")
        return []
    objects = [row for row in rows if isinstance(row, dict)]
    if len(objects) != len(rows):
        found.error(EXAMPLES, "every example row must be an object")
        return []
    return objects


def check_examples(
    root: Path, scenarios: dict[str, str], placeholders: Placeholders, found: Findings
) -> None:
    rows = example_rows(read_object(root, EXAMPLES, found), found)
    humans = [row for row in rows if "order" not in row]
    if rows and len(humans) != HUMAN_ROWS:
        found.error(EXAMPLES, "exactly one example must be the talk-to-a-human row")
    for row in rows:
        expected = HUMAN_ROW_KEYS if "order" not in row else ORDER_ROW_KEYS
        if frozenset(row) != expected:
            found.error(
                EXAMPLES, f"row {row.get('id')!r} must have exactly the keys {sorted(expected)}"
            )
        elif "order" in row:
            check_order_row(row, scenarios, placeholders, found)
    ids = [row.get("id") for row in rows]
    if len(set(map(str, ids))) != len(ids):
        found.error(EXAMPLES, "example ids must be unique")


def public_rows(root: Path, found: Findings) -> list[JsonObject]:
    document = read_object(root, PUBLIC_ORDERS, found)
    if document is None:
        return []
    rows = document.get("orders")
    if not isinstance(rows, list) or len(rows) != PUBLIC_ROW_COUNT:
        found.error(PUBLIC_ORDERS, f"orders must be a list of {PUBLIC_ROW_COUNT} rows")
        return []
    objects = [row for row in rows if isinstance(row, dict)]
    if len(objects) != len(rows):
        found.error(PUBLIC_ORDERS, "every public order row must be an object")
        return []
    return objects


def read_public_pin(root: Path, found: Findings) -> set[str] | None:
    document = read_object(root, PUBLIC_ORDERS_PIN, found)
    if document is None:
        return None
    orders = document.get("orders")
    names = (
        [order for order in orders if isinstance(order, str) and canonical_or_none(order) == order]
        if isinstance(orders, list)
        else []
    )
    if len(names) != PUBLIC_ROW_COUNT or len(set(names)) != PUBLIC_ROW_COUNT or names != orders:
        found.error(
            PUBLIC_ORDERS_PIN,
            f"pin must hold exactly {PUBLIC_ROW_COUNT} distinct canonical order names",
        )
        return None
    return set(names)


def check_public_membership(
    rows: list[JsonObject], examples: list[JsonObject], pinned: set[str] | None, found: Findings
) -> None:
    orders = {str(row.get("order")) for row in rows}
    if pinned is not None and orders != pinned:
        found.error(
            PUBLIC_ORDERS,
            "public orders must be exactly the pinned set; "
            f"unexpected: {sorted(orders - pinned)}, missing: {sorted(pinned - orders)}",
        )
    for row in examples:
        if "order" in row and str(row["order"]) not in orders:
            found.error(EXAMPLES, f"example order {row['order']} is not in the public orders")
    emails = [str(row.get("email")) for row in rows]
    if len(set(emails)) != len(emails):
        found.error(PUBLIC_ORDERS, "public emails must be unique")


def check_public_orders(
    root: Path,
    scenarios: dict[str, str],
    placeholders: Placeholders,
    found: Findings,
    pinned: set[str] | None,
) -> None:
    rows = public_rows(root, found)
    document = read_object(root, EXAMPLES, found)
    examples = example_rows(document, found)
    check_public_membership(rows, examples, pinned, found)
    emails = {str(row.get("order")): row.get("email") for row in examples if "order" in row}
    for row in rows:
        if frozenset(row) != ORDER_ROW_KEYS:
            found.error(
                PUBLIC_ORDERS,
                f"row {row.get('id')!r} must have exactly the keys {sorted(ORDER_ROW_KEYS)}",
            )
            continue
        check_order_row(row, scenarios, placeholders, found, PUBLIC_ORDERS)
        order = row["order"]
        if canonical_or_none(order) != order:
            found.error(PUBLIC_ORDERS, "public orders must use canonical order numbers")
        if str(order) in emails and row["email"] != emails[str(order)]:
            found.error(PUBLIC_ORDERS, f"the email of {order} must match example_orders.json")
    for key in ("order", "id"):
        values = [str(row.get(key)) for row in rows]
        if len(set(values)) != len(values):
            found.error(PUBLIC_ORDERS, f"public {key} values must be unique")


def check_runtime(root: Path, placeholders: Placeholders, found: Findings) -> None:
    document = read_object(root, RUNTIME, found)
    if document is None:
        return
    turnstile = document.get("turnstile")
    if frozenset(document) != RUNTIME_KEYS or not isinstance(turnstile, dict):
        found.error(RUNTIME, f"the only top-level key is {sorted(RUNTIME_KEYS)}")
        return
    if frozenset(turnstile) != TURNSTILE_KEYS:
        found.error(RUNTIME, f"turnstile must have exactly the keys {sorted(TURNSTILE_KEYS)}")
        return
    sitekey, action = turnstile["sitekey"], turnstile["action"]
    if not isinstance(sitekey, str) or placeholders.sitekey_shape.fullmatch(sitekey) is None:
        found.error(
            RUNTIME, "sitekey is not a Turnstile site key (a secret key never belongs here)"
        )
    elif placeholders.sitekey.search(sitekey):
        found.placeholder(RUNTIME, "the sitekey is still a Cloudflare test key")
    if not isinstance(action, str) or ACTION.fullmatch(action) is None:
        found.error(RUNTIME, "action must be a lowercase slug")


def check_all(root: Path) -> Findings:
    found = Findings()
    check_pricing(root, found)
    pinned = read_public_pin(root, found)
    scenarios = plan_scenarios(root, found)
    placeholders = read_placeholders(root, found)
    if placeholders is not None:
        check_examples(root, scenarios, placeholders, found)
        check_public_orders(root, scenarios, placeholders, found, pinned)
        check_runtime(root, placeholders, found)
    return found


def main(argv: Sequence[str] | None = None) -> int:
    parser = guardlib.make_parser("Validate the data files the product page reads.")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args(argv)
    found = check_all(args.root.resolve())
    for item in found.pending:
        sys.stderr.write(f"note: {item.path}: {item.reason}; the release lock blocks it\n")
    return guardlib.report(found.errors + (found.pending if args.strict else []))


if __name__ == "__main__":
    sys.exit(main())
