import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from gisting.kb.aliases import ALIASES_FILE, load_aliases
from gisting.kb.bm25 import build_index, search
from gisting.kb.entries import ENTRIES_FILE, load_entries
from gisting.kb.jsonvalue import Json, KbDataError
from gisting.kb.params import PARAMS_FILE, Bm25Params, load_params

USAGE_EXIT = 2
DATA_EXIT = 1


class InvalidRequest(ValueError):
    pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gisting.kb")
    commands = parser.add_subparsers(dest="command", required=True)
    find = commands.add_parser(
        "search", help="search the knowledge base for one query read from stdin"
    )
    find.add_argument("--entries", type=Path, default=ENTRIES_FILE)
    find.add_argument("--params", type=Path, default=PARAMS_FILE)
    find.add_argument("--aliases", type=Path, default=ALIASES_FILE)
    return parser


def read_request(params: Bm25Params) -> tuple[str, int]:
    try:
        document: Json = json.load(sys.stdin)
    except (ValueError, RecursionError) as error:
        message = f"stdin is not valid JSON: {error}"
        raise InvalidRequest(message) from error
    if not isinstance(document, dict) or not isinstance(document.get("query"), str):
        message = 'stdin must be a JSON object with a "query" string'
        raise InvalidRequest(message)
    query = document["query"]
    top_k = document.get("top_k", params.default_top_k)
    if not isinstance(top_k, int) or isinstance(top_k, bool) or top_k < 1:
        message = '"top_k" must be a positive integer'
        raise InvalidRequest(message)
    return str(query), min(top_k, params.max_top_k)


def run_search(args: argparse.Namespace) -> int:
    entries = load_entries(args.entries)
    params = load_params(args.params)
    query, top_k = read_request(params)
    index = build_index(entries, params, load_aliases(entries, args.aliases))
    hits = search(index, query, top_k)
    sys.stdout.write(json.dumps({"hits": [asdict(hit) for hit in hits]}, sort_keys=True) + "\n")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(sys.argv[1:] if argv is None else list(argv))
    try:
        return run_search(args)
    except InvalidRequest as error:
        sys.stderr.write(f"gisting.kb: InvalidRequest: {error}\n")
        return USAGE_EXIT
    except KbDataError as error:
        sys.stderr.write(f"gisting.kb: KbDataError: {error}\n")
        return DATA_EXIT
