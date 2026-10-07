import argparse
import json
import os
import sys
import time
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from gisting.shopify.apply_order import ApplyContext, OrderOutcome, Status, apply_order
from gisting.shopify.cli_transport import CliTransport
from gisting.shopify.client import AdminClient
from gisting.shopify.demo_config import DistributionConfig, load_config
from gisting.shopify.demo_email import MissingSecret, email_secret
from gisting.shopify.dry_run import dry_run, render_report
from gisting.shopify.email_rewrite import rewrite_email
from gisting.shopify.email_rewrite_report import Verdict, dry_run_emails, render_email_report
from gisting.shopify.env_file import DEFAULT_ENV_FILE, load_env_file
from gisting.shopify.eta_refresh import FAILURES, RefreshBatch, RefreshOptions, refresh_json
from gisting.shopify.http_transport import HttpTransport
from gisting.shopify.ledger import Ledger
from gisting.shopify.order_name import InvalidOrderName, canonical_order_name
from gisting.shopify.plan import PlanEntry, PlanFormatError, ShipmentPlan, load_plan
from gisting.shopify.readonly import ReadOnlyTransport
from gisting.shopify.run_plan import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_BATCH_WAIT_SECONDS,
    DEFAULT_MAX_FAILURES,
    HTTP_BATCH_WAIT_SECONDS,
    ApplyOne,
    Pacing,
    RunStopped,
    run_plan,
)
from gisting.shopify.set_state import UnknownOrder, UnknownState, set_state
from gisting.shopify.transport import Transport

DEFAULT_PLAN = Path("data/demo-orders/shipment-plan-v1.json")
DEFAULT_LEDGER = Path("artifacts/shipment-plan-v1/ledger.jsonl")
DEFAULT_APP_PATH = Path("shopify-app/gisting-order-agent")
OK_STATUSES = frozenset({
    Status.APPLIED,
    Status.SKIPPED_TAGGED,
    Status.SKIPPED_SAME_STATE,
    Status.UNCHANGED,
})
USAGE_EXIT = 2
FAILURE_EXIT = 1
CLIENT_SECRET_ENV = "SHOPIFY_CLIENT_SECRET"
BLOCKING_VERDICTS = frozenset({Verdict.UNREADABLE, Verdict.REFUSED})


class UsageError(Exception):
    pass


@dataclass(frozen=True)
class Runtime:
    transport: Transport | None = None
    sleep: Callable[[float], None] = time.sleep
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)


def common_parser(description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="demo_apply", description=description)
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument("--app-path", type=Path, default=DEFAULT_APP_PATH)
    parser.add_argument("--transport", choices=("http", "cli"), default="http")
    return parser


def run_parser(description: str, *, only: bool = True) -> argparse.ArgumentParser:
    parser = common_parser(description)
    parser.add_argument("--dry-run", action="store_true")
    if only:
        parser.add_argument("--only")
    parser.add_argument("--batch-size", type=positive_int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument(
        "--batch-wait",
        type=float,
        help=(
            f"seconds between batches (default {DEFAULT_BATCH_WAIT_SECONDS:g} with "
            f"--transport cli, {HTTP_BATCH_WAIT_SECONDS:g} with http: cost-point throttling is "
            "driven by throttleStatus and a 429 backs off, so no long fixed wait is needed)"
        ),
    )
    parser.add_argument("--max-failures", type=positive_int, default=DEFAULT_MAX_FAILURES)
    return parser


def apply_parser() -> argparse.ArgumentParser:
    return run_parser("Apply the demo shipment plan to the dev store.")


def rewrite_parser() -> argparse.ArgumentParser:
    return run_parser("Rewrite only the demo emails of the planned orders, with read-back.")


def set_state_parser() -> argparse.ArgumentParser:
    parser = common_parser("Move one order to a shipment state.")
    parser.add_argument("order")
    parser.add_argument("state")
    return parser


def positive_int(raw: str) -> int:
    value = int(raw)
    if value < 1:
        message = "must be at least 1"
        raise argparse.ArgumentTypeError(message)
    return value


def load_inputs(plan_path: Path, env_file: Path | None) -> tuple[ShipmentPlan, str]:
    if not load_env_file(env_file or DEFAULT_ENV_FILE) and env_file is not None:
        message = f"env file not found: {env_file}"
        raise UsageError(message)
    try:
        plan = load_plan(plan_path.read_text(encoding="utf-8"))
        return plan, email_secret()
    except (OSError, PlanFormatError, MissingSecret) as error:
        message = f"{type(error).__name__}: {error}"
        raise UsageError(message) from error


def select_entries(plan: ShipmentPlan, only: str | None) -> list[PlanEntry]:
    if only is None:
        return list(plan.entries)
    if not only.strip():
        message = "--only is empty; omit it to select every order"
        raise UsageError(message)
    try:
        wanted = {canonical_order_name(item) for item in only.split(",")}
    except InvalidOrderName as error:
        message = f"invalid order in --only: {error}"
        raise UsageError(message) from error
    chosen = [entry for entry in plan.entries if entry.order in wanted]
    if len(chosen) != len(wanted):
        message = "--only names an order that is not in the plan"
        raise UsageError(message)
    return chosen


def summarize(outcomes: Sequence[OrderOutcome]) -> str:
    return json.dumps(dict(Counter(outcome.status.value for outcome in outcomes)), sort_keys=True)


def build_transport(args: argparse.Namespace) -> Transport:
    if args.transport == "cli":
        return CliTransport(args.app_path)
    secret = os.environ.get("SHOPIFY_CLIENT_SECRET", "")
    if not secret:
        message = f"{CLIENT_SECRET_ENV} is not set (put it in the env file)"
        raise UsageError(message)
    return HttpTransport(secret)


def batch_wait(args: argparse.Namespace) -> float:
    if args.batch_wait is not None:
        return args.batch_wait
    return DEFAULT_BATCH_WAIT_SECONDS if args.transport == "cli" else HTTP_BATCH_WAIT_SECONDS


def make_context(
    args: argparse.Namespace, plan: ShipmentPlan, secret: str, runtime: Runtime, *, read_only: bool
) -> ApplyContext:
    transport = runtime.transport or build_transport(args)
    guarded = ReadOnlyTransport(transport) if read_only else transport
    client = AdminClient(guarded, sleep=runtime.sleep)
    return ApplyContext(client, Ledger(args.ledger), plan, secret, runtime.clock)


def execute(
    ctx: ApplyContext,
    entries: Sequence[PlanEntry],
    pacing: Pacing,
    args: argparse.Namespace,
    apply: ApplyOne,
) -> int:
    try:
        outcomes = run_plan(ctx, entries, pacing, args.max_failures, apply)
    except RunStopped as stopped:
        sys.stderr.write(f"demo_apply: run stopped: {stopped.reason}\n")
        sys.stdout.write(summarize(stopped.outcomes) + "\n")
        return FAILURE_EXIT
    sys.stdout.write(summarize(outcomes) + "\n")
    return 0 if all(outcome.status in OK_STATUSES for outcome in outcomes) else FAILURE_EXIT


def run_apply(argv: Sequence[str], runtime: Runtime) -> int:
    args = apply_parser().parse_args(argv)
    plan, secret = load_inputs(args.plan, args.env_file)
    entries = select_entries(plan, args.only)
    ctx = make_context(args, plan, secret, runtime, read_only=args.dry_run)
    pacing = Pacing(args.batch_size, batch_wait(args), runtime.sleep)
    if args.dry_run:
        rows = dry_run(ctx.client, plan, entries, pacing, secret)
        sys.stdout.write(render_report(rows, len(plan.entries)))
        return FAILURE_EXIT if any(row.current == "?" for row in rows) else 0
    return execute(ctx, entries, pacing, args, apply_order)


def run_rewrite_emails(argv: Sequence[str], runtime: Runtime) -> int:
    args = rewrite_parser().parse_args(argv)
    plan, secret = load_inputs(args.plan, args.env_file)
    entries = select_entries(plan, args.only)
    ctx = make_context(args, plan, secret, runtime, read_only=args.dry_run)
    pacing = Pacing(args.batch_size, batch_wait(args), runtime.sleep)
    if args.dry_run:
        rows = dry_run_emails(ctx.client, entries, pacing, secret)
        sys.stdout.write(render_email_report(rows, len(plan.entries)))
        return FAILURE_EXIT if any(row.verdict in BLOCKING_VERDICTS for row in rows) else 0
    return execute(ctx, entries, pacing, args, rewrite_email)


def run_set_state(argv: Sequence[str], runtime: Runtime, config: DistributionConfig) -> int:
    args = set_state_parser().parse_args(argv)
    plan, secret = load_inputs(args.plan, args.env_file)
    ctx = make_context(args, plan, secret, runtime, read_only=False)
    try:
        outcome = set_state(ctx, config, args.order, args.state)
    except (UnknownOrder, UnknownState, InvalidOrderName) as error:
        message = f"{type(error).__name__}: {error}"
        raise UsageError(message) from error
    sys.stdout.write(summarize([outcome]) + "\n")
    return 0 if outcome.status in OK_STATUSES else FAILURE_EXIT


def refresh_parser() -> argparse.ArgumentParser:
    parser = run_parser("Refresh stale demo shipment ETAs, with read-back.", only=False)
    parser.add_argument("order", nargs="?")
    parser.add_argument("--orders")
    parser.add_argument("--all-stale", action="store_true")
    parser.add_argument("--eta-days", metavar="N", help="set ETA to now plus N days")
    parser.add_argument("--force", action="store_true", help="refresh even a fresh ETA")
    return parser


def refresh_options(args: argparse.Namespace, config: DistributionConfig) -> RefreshOptions:
    if args.force and args.all_stale:
        message = "--force cannot be combined with --all-stale"
        raise UsageError(message)
    days = None
    if args.eta_days is not None:
        message = (
            f"--eta-days must be an integer in the range "
            f"{config.eta_days_min}..{config.eta_days_max} (inclusive)"
        )
        try:
            days = int(args.eta_days)
        except ValueError as error:
            raise UsageError(message) from error
        if not config.eta_days_min <= days <= config.eta_days_max:
            raise UsageError(message)
    return RefreshOptions(days, args.force)


def run_refresh_eta(argv: Sequence[str], runtime: Runtime) -> int:
    args = refresh_parser().parse_args(argv)
    config = load_config()
    options = refresh_options(args, config)
    selectors = (args.order is not None, args.orders is not None, args.all_stale)
    if sum(selectors) != 1:
        message = "exactly one of order, --orders, or --all-stale is required"
        raise UsageError(message)
    plan, secret = load_inputs(args.plan, args.env_file)
    try:
        selector = canonical_order_name(args.order) if args.order is not None else args.orders
    except InvalidOrderName as error:
        raise UsageError(str(error)) from error
    entries = select_entries(plan, selector)
    if args.all_stale:
        entries = [entry for entry in entries if entry.event is not None]
    ctx = make_context(args, plan, secret, runtime, read_only=args.dry_run)
    pacing = Pacing(args.batch_size, batch_wait(args), runtime.sleep)
    batch = RefreshBatch(ctx, config, args.dry_run, options)
    outcomes = batch.run(entries, pacing, args.max_failures)
    report = refresh_json(outcomes)
    if batch.stopped is not None:
        sys.stderr.write(f"demo_apply: run stopped: {batch.stopped}\n")
        report["stopped"] = batch.stopped
    sys.stdout.write(json.dumps(report, sort_keys=True) + "\n")
    return FAILURE_EXIT if any(outcome.result in FAILURES for outcome in outcomes) else 0


def main(argv: Sequence[str] | None = None, runtime: Runtime | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    runtime = runtime or Runtime()
    try:
        if args[:1] == ["refresh-eta"]:
            return run_refresh_eta(args[1:], runtime)
        if args[:1] == ["set-state"]:
            return run_set_state(args[1:], runtime, load_config())
        if args[:1] == ["rewrite-emails"]:
            return run_rewrite_emails(args[1:], runtime)
        return run_apply(args, runtime)
    except UsageError as error:
        sys.stderr.write(f"demo_apply: {error}\n")
        return USAGE_EXIT


if __name__ == "__main__":
    sys.exit(main())
