import json
from pathlib import Path

from gisting.kb.aliases import ALIASES_FILE, load_aliases
from gisting.kb.bm25 import Hit, build_index, search
from gisting.kb.entries import ENTRIES_FILE, load_entries
from gisting.kb.jsonvalue import KB_DIR, KbDataError
from gisting.kb.params import Bm25Params, load_params
from gisting.shopify.jsonvalue import Json, JsonObject
from gisting.tools.lookup_order import ToolResponse
from gisting.tools.outcomes import (
    PolicyFound,
    PolicyHit,
    PolicyNoMatch,
    PolicyOutcome,
    PolicyUnavailable,
)
from gisting.tools.trace import InternalTrace, PublicOutcome, PublicTrace, Trace

TOOL_NAME = "search_policy"
STATUS_FOUND = "policy_found"
STATUS_NO_MATCH = "policy_no_match"
STATUS_UNAVAILABLE = "policy_unavailable"
PARAMS_FILE = KB_DIR / "bm25-v3.json"


class InvalidPolicyCall(ValueError):
    pass


def query_argument(arguments: JsonObject) -> str:
    query = arguments.get("query")
    if set(arguments) != {"query"} or not isinstance(query, str):
        message = 'arguments must be exactly {"query": <string>}'
        raise InvalidPolicyCall(message)
    return query


def passes(hit: Hit, params: Bm25Params) -> bool:
    return hit.score >= params.min_score and hit.matched_terms >= params.min_matched_terms


def render_policy(outcome: PolicyOutcome) -> JsonObject:
    if isinstance(outcome, PolicyFound):
        hits: list[Json] = [
            {"id": hit.id, "category": hit.category, "title": hit.title, "answer": hit.answer}
            for hit in outcome.hits
        ]
        return {"status": STATUS_FOUND, "hits": hits}
    if isinstance(outcome, PolicyNoMatch):
        return {"status": STATUS_NO_MATCH}
    return {"status": STATUS_UNAVAILABLE}


def candidates_json(candidates: tuple[Hit, ...]) -> str:
    return json.dumps([
        {"id": hit.id, "score": hit.score, "matched_terms": hit.matched_terms} for hit in candidates
    ])


def respond(outcome: PolicyOutcome, session_id: str, detail: str) -> ToolResponse:
    unavailable = isinstance(outcome, PolicyUnavailable)
    internal = InternalTrace(
        tool=TOOL_NAME,
        session_id=session_id,
        order_number=None,
        result_type=type(outcome).__name__,
        cache_hit=None,
        detail=detail,
        failures_before=0,
    )
    public = PublicTrace(
        TOOL_NAME, None, PublicOutcome.UNAVAILABLE if unavailable else PublicOutcome.COMPLETED
    )
    return ToolResponse(render_policy(outcome), Trace(internal, public))


class SearchPolicy:
    def __init__(
        self,
        entries_file: Path = ENTRIES_FILE,
        params_file: Path = PARAMS_FILE,
        aliases_file: Path | None = ALIASES_FILE,
    ) -> None:
        self._entries_file = entries_file
        self._params_file = params_file
        self._aliases_file = aliases_file

    def call(self, arguments: JsonObject, session_id: str) -> ToolResponse:
        query = query_argument(arguments)
        try:
            params = load_params(self._params_file)
            entries = load_entries(self._entries_file)
            aliases = load_aliases(entries, self._aliases_file) if self._aliases_file else None
            index = build_index(entries, params, aliases)
        except KbDataError as error:
            reason = f"{type(error).__name__}: {error}"
            return respond(PolicyUnavailable(reason), session_id, reason)
        candidates = search(index, query, params.default_top_k)
        kept = tuple(
            PolicyHit(hit.id, hit.category, hit.title, hit.answer)
            for hit in candidates
            if passes(hit, params)
        )
        outcome = PolicyFound(kept) if kept else PolicyNoMatch()
        return respond(outcome, session_id, candidates_json(candidates))
