import argparse
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field

from gisting.agent.assemble import GIST_MODE, Loaded, assemble_deps, production_tools
from gisting.agent.batch import run_batch
from gisting.agent.identity import model_identity
from gisting.agent.state import AgentDeps
from gisting.agent.turn import run_turn
from gisting.agent.wire import parse_request, wire
from gisting.model_server.config import ModelConfig, load_config
from gisting.model_server.interface import Model
from gisting.prompt.messages import Message
from gisting.prompt.tokenizer import PromptTokenizer, TokenizerUnavailable
from gisting.shopify.demo_apply import UsageError
from gisting.shopify.jsonvalue import JsonObject
from gisting.tools.cli import Runtime as ToolsRuntime
from gisting.tools.cli import add_transport_arguments, build_tool, read_stdin_json
from gisting.tools.policy import PolicyError, load_policy

USAGE_EXIT = 2
FALLBACK_EXIT = 1
MODES = ("full", GIST_MODE)


@dataclass(frozen=True)
class Runtime:
    tools: ToolsRuntime = ToolsRuntime()
    model: Model | None = None
    tokenizer: PromptTokenizer | None = None
    gist_count: int | None = None
    gist_run_id: str | None = None
    identity: JsonObject = field(default_factory=lambda: {})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gisting.agent")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="answer one turn read from stdin")
    run.add_argument("--internal", action="store_true")
    run.add_argument("--batch", action="store_true", help="one request per stdin line")
    run.add_argument("--mode", choices=MODES, default="full", help="gist reads GISTING_GIST_DIR")
    add_transport_arguments(run)
    return parser


def read_request() -> tuple[str, list[Message]]:
    return parse_request(read_stdin_json())


def load_model(config: ModelConfig, mode: str) -> Loaded:
    if mode == GIST_MODE and config.gist_dir is None:
        message = "GISTING_GIST_DIR must point at a Gist artifact for --mode gist"
        raise UsageError(message)
    try:
        from gisting.model_server.transformers_backend import TransformersModel

        model = TransformersModel.load(config, config.gist_dir if mode == GIST_MODE else None)
        tokenizer = PromptTokenizer.from_dir(config.model_dir)
    except (ImportError, OSError, TokenizerUnavailable, ValueError) as error:
        message = f"cannot load the model from {config.model_dir}: {type(error).__name__}: {error}"
        raise UsageError(message) from error
    identity = model_identity(config.model_dir, model.gist_manifest)
    if model.gist is None or model.gist_manifest is None:
        return Loaded(model, tokenizer, identity=identity)
    return Loaded(model, tokenizer, model.gist.count, model.gist_manifest.run_id, identity)


def injected_or_loaded(mode: str, runtime: Runtime) -> Loaded:
    if runtime.model is None or runtime.tokenizer is None:
        return load_model(load_config(os.environ), mode)
    return Loaded(
        runtime.model, runtime.tokenizer, runtime.gist_count, runtime.gist_run_id, runtime.identity
    )


def build_deps(args: argparse.Namespace, runtime: Runtime) -> AgentDeps:
    tools = production_tools(build_tool(args, runtime.tools))
    loaded = injected_or_loaded(args.mode, runtime)
    try:
        lookup = load_policy()
    except (PolicyError, OSError) as error:
        message = f"{type(error).__name__}: {error}"
        raise UsageError(message) from error
    return assemble_deps(loaded, args.mode, tools, lookup)


def run(args: argparse.Namespace, runtime: Runtime) -> int:
    if args.batch:
        return run_batch(build_deps(args, runtime), sys.stdin, sys.stdout, internal=args.internal)
    session_id, messages = read_request()
    result = run_turn(build_deps(args, runtime), session_id, messages)
    sys.stdout.write(wire(result, internal=args.internal) + "\n")
    if result.fallback_reason is not None:
        sys.stderr.write(f"gisting.agent: fallback: {result.fallback_reason.value}\n")
        return FALLBACK_EXIT
    return 0


def main(argv: Sequence[str] | None = None, runtime: Runtime | None = None) -> int:
    args = build_parser().parse_args(sys.argv[1:] if argv is None else list(argv))
    try:
        return run(args, runtime or Runtime())
    except UsageError as error:
        sys.stderr.write(f"gisting.agent: {error}\n")
        return USAGE_EXIT
