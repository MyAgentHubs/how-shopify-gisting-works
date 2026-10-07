import argparse
import json
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from gisting.shopify.client import AdminClient
from gisting.shopify.demo_apply import DEFAULT_APP_PATH, UsageError, build_transport
from gisting.shopify.demo_email import MissingSecret, email_secret
from gisting.shopify.env_file import DEFAULT_ENV_FILE, load_env_file
from gisting.shopify.jsonvalue import Json, JsonObject
from gisting.shopify.plan_transport import LocalSourceError, PlanTransport, load_local_source
from gisting.shopify.transport import Transport
from gisting.tools.attempts import InMemoryFailureCounter
from gisting.tools.cache import InMemoryOrderCache
from gisting.tools.factory import build_lookup
from gisting.tools.handoff import TOOL_NAME as HANDOFF_TOOL
from gisting.tools.handoff import HandoffToHuman
from gisting.tools.lookup_order import LookupOrder, ToolResponse
from gisting.tools.mock import InvalidMockCall, ReferenceTool
from gisting.tools.policy import PolicyError, load_policy
from gisting.tools.reminder import TOOL_NAME as PRIORITY_TOOL
from gisting.tools.reminder import SendShippingReminder
from gisting.tools.search_policy import TOOL_NAME as POLICY_TOOL
from gisting.tools.search_policy import InvalidPolicyCall, SearchPolicy
from gisting.tools.trace import PublicOutcome, internal_json, public_json

TOOLS = ("lookup_order", HANDOFF_TOOL, PRIORITY_TOOL, POLICY_TOOL)
MOCKS: dict[str, Callable[[], ReferenceTool]] = {
    HANDOFF_TOOL: HandoffToHuman,
    PRIORITY_TOOL: SendShippingReminder,
}
USAGE_EXIT = 2
UNAVAILABLE_EXIT = 1


@dataclass(frozen=True)
class Runtime:
    transport: Transport | None = None
    sleep: Callable[[float], None] = time.sleep
    search: SearchPolicy | None = None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gisting.tools")
    commands = parser.add_subparsers(dest="command", required=True)
    call = commands.add_parser("call", help="run one tool call read from stdin")
    call.add_argument("tool", choices=TOOLS)
    call.add_argument("--internal", action="store_true")
    add_transport_arguments(call)
    return parser


def add_transport_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--transport", choices=("http", "cli", "local"), default="http")
    parser.add_argument("--app-path", type=Path, default=DEFAULT_APP_PATH)


def read_stdin_json() -> Json:
    try:
        return json.load(sys.stdin)
    except RecursionError as error:
        message = "stdin JSON is nested too deeply"
        raise UsageError(message) from error
    except ValueError as error:
        message = f"stdin is not valid JSON: {error}"
        raise UsageError(message) from error


def read_request() -> tuple[JsonObject, str]:
    document = read_stdin_json()
    if not isinstance(document, dict):
        message = "stdin must be a JSON object"
        raise UsageError(message)
    arguments, session_id = document.get("arguments"), document.get("session_id")
    if not isinstance(arguments, dict) or not isinstance(session_id, str) or not session_id:
        message = 'stdin needs an "arguments" object and a non-empty "session_id" string'
        raise UsageError(message)
    return arguments, session_id


def pick_transport(args: argparse.Namespace, runtime: Runtime, secret: str) -> Transport:
    if runtime.transport is not None:
        return runtime.transport
    if args.transport != "local":
        return build_transport(args)
    try:
        source = load_local_source()
    except LocalSourceError as error:
        message = f"{type(error).__name__}: {error}"
        raise UsageError(message) from error
    return PlanTransport(source.plan, secret, source.seeded_at)


def build_tool(args: argparse.Namespace, runtime: Runtime) -> LookupOrder:
    if not load_env_file(args.env_file or DEFAULT_ENV_FILE) and args.env_file is not None:
        message = f"env file not found: {args.env_file}"
        raise UsageError(message)
    try:
        secret = email_secret()
        policy = load_policy()
    except (MissingSecret, PolicyError) as error:
        message = f"{type(error).__name__}: {error}"
        raise UsageError(message) from error
    client = AdminClient(pick_transport(args, runtime, secret), sleep=runtime.sleep)
    cache = InMemoryOrderCache(policy.cache_ttl_seconds)
    # see: docs/decisions/0001-tools-cli-is-stateless.md
    return build_lookup(client, cache, InMemoryFailureCounter(policy.failure_limit), policy, secret)


def wire(response: ToolResponse, *, internal: bool) -> str:
    document: JsonObject = {"result": response.result, "trace": public_json(response.trace.public)}
    if internal:
        document["internal"] = internal_json(response.trace.internal)
    return json.dumps(document, sort_keys=True)


def respond(args: argparse.Namespace, runtime: Runtime) -> ToolResponse:
    arguments, session_id = read_request()
    try:
        if args.tool == POLICY_TOOL:
            return (runtime.search or SearchPolicy()).call(arguments, session_id)
        if args.tool in MOCKS:
            return MOCKS[args.tool]().call(arguments, session_id)
    except (InvalidMockCall, InvalidPolicyCall) as error:
        raise UsageError(str(error)) from error
    return build_tool(args, runtime).call(arguments, session_id)


def run_call(args: argparse.Namespace, runtime: Runtime) -> int:
    response = respond(args, runtime)
    sys.stdout.write(wire(response, internal=args.internal) + "\n")
    if response.trace.public.outcome is PublicOutcome.UNAVAILABLE:
        reason = response.trace.internal.detail
        sys.stderr.write(f"gisting.tools: {args.tool} unavailable: {reason}\n")
        return UNAVAILABLE_EXIT
    return 0


def main(argv: Sequence[str] | None = None, runtime: Runtime | None = None) -> int:
    args = build_parser().parse_args(sys.argv[1:] if argv is None else list(argv))
    try:
        return run_call(args, runtime or Runtime())
    except UsageError as error:
        sys.stderr.write(f"gisting.tools: {error}\n")
        return USAGE_EXIT
