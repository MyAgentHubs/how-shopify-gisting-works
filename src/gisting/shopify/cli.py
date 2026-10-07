import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TypeGuard

from gisting.shopify.demo_apply import DEFAULT_PLAN
from gisting.shopify.demo_email import MissingSecret, demo_email, email_secret
from gisting.shopify.env_file import DEFAULT_ENV_FILE, load_env_file
from gisting.shopify.example_emails import EXAMPLES_KEY, ExampleOrdersError, fill_example_emails
from gisting.shopify.jsonvalue import Json, JsonObject
from gisting.shopify.order_name import InvalidOrderName, canonical_order_name
from gisting.shopify.plan import PlanFormatError, load_plan

USAGE_EXIT = 2


class UsageError(ValueError):
    pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gisting.shopify")
    commands = parser.add_subparsers(dest="command", required=True)
    emails = commands.add_parser("demo-emails", help="stdin order numbers, stdout their emails")
    emails.add_argument("--env-file", type=Path)
    fill = commands.add_parser(
        "fill-example-emails", help="write the demo email of each example order into its file"
    )
    fill.add_argument("--orders", type=Path, required=True)
    fill.add_argument("--rows-key", default=EXAMPLES_KEY)
    fill.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    fill.add_argument("--env-file", type=Path)
    return parser


def is_order_object(parsed: Json) -> TypeGuard[JsonObject]:
    return isinstance(parsed, dict) and "order_number" in parsed


def order_of(number: int, line: str) -> str:
    try:
        parsed = json.loads(line)
    except json.JSONDecodeError as error:
        message = f"line {number}: not JSON"
        raise UsageError(message) from error
    order = parsed["order_number"] if is_order_object(parsed) else None
    if not isinstance(order, str):
        message = f"line {number}: expected an object with a string order_number"
        raise UsageError(message)
    try:
        canonical_order_name(order)
    except InvalidOrderName as error:
        message = f"line {number}: order_number is not an order number"
        raise UsageError(message) from error
    return order


def read_orders(lines: Sequence[str]) -> list[str]:
    return [order_of(number, line) for number, line in enumerate(lines, start=1) if line.strip()]


def load_secret(env_file: Path | None) -> str:
    if not load_env_file(env_file or DEFAULT_ENV_FILE) and env_file is not None:
        message = f"env file not found: {env_file}"
        raise UsageError(message)
    try:
        return email_secret()
    except MissingSecret as error:
        message = f"{error} is not set"
        raise UsageError(message) from error


def run_demo_emails(args: argparse.Namespace) -> int:
    secret = load_secret(args.env_file)
    rows: list[JsonObject] = [
        {"order_number": order, "email": demo_email(secret, order)}
        for order in read_orders(sys.stdin.read().splitlines())
    ]
    sys.stdout.write("".join(json.dumps(row) + "\n" for row in rows))
    return 0


def planned_orders(plan_file: Path) -> frozenset[str]:
    try:
        plan = load_plan(plan_file.read_text(encoding="utf-8"))
    except (OSError, PlanFormatError) as error:
        message = f"cannot read the plan: {plan_file}"
        raise UsageError(message) from error
    return frozenset(entry.order for entry in plan.entries)


def run_fill_example_emails(args: argparse.Namespace) -> int:
    secret = load_secret(args.env_file)
    try:
        filled = fill_example_emails(args.orders, planned_orders(args.plan), secret, args.rows_key)
    except ExampleOrdersError as error:
        raise UsageError(str(error)) from error
    sys.stdout.write("".join(f"{order} filled\n" for order in filled))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(sys.argv[1:] if argv is None else list(argv))
    try:
        if args.command == "fill-example-emails":
            return run_fill_example_emails(args)
        return run_demo_emails(args)
    except UsageError as error:
        sys.stderr.write(f"gisting.shopify: {error}\n")
        return USAGE_EXIT
