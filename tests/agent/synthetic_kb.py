import json
from dataclasses import replace
from pathlib import Path

from agent_support import Rig, SpyTool, rig, tool_call
from search_support import SCHEMA, SEARCH

from gisting.agent.policy import AgentPolicy
from gisting.agent.state import ToolRunner
from gisting.prompt.phrases import load_phrases
from gisting.shopify.jsonvalue import JsonObject
from gisting.tools.search_policy import SearchPolicy

NO_MATCH_PHRASE = "That is not something I can answer from our store policies."
OFFER = load_phrases().handoff_offer
NO_MATCH_REPLY = f"{NO_MATCH_PHRASE} {OFFER}"
WARRANTY = (
    "The zorblax warranty lasts 18 months from Friday of purchase. "
    "Claims take 2 to 4 business days, and the claims line is 800123."
)
REPAIR = "Repairs of the zorblax are free within 30 days of the claim."
PARTS = "Spare parts for the zorblax ship in 5 business days."
ENTRIES = {
    "kb-zz-warranty": ("Zorblax warranty length", WARRANTY),
    "kb-zz-repair": ("Zorblax repair service", REPAIR),
    "kb-zz-parts": ("Zorblax spare parts", PARTS),
    "kb-zz-quasar": ("Quasar delivery", "Quasar parcels travel by rail."),
}
PARAMS: JsonObject = {
    "k1": 1.5,
    "b": 0.75,
    "default_top_k": 3,
    "max_top_k": 10,
    "stopwords": [],
    "min_score": 0.0,
    "min_matched_terms": 1,
}
ASKED = "How long is the zorblax warranty?"
SEARCH_CALL = tool_call(SEARCH, query="zorblax warranty")
OFF_TOPIC = "Do you sell zebra unicorns?"
OFF_TOPIC_CALL = tool_call(SEARCH, query="zebra unicorns")


def entry_lines(entries: dict[str, tuple[str, str]] = ENTRIES) -> str:
    rows = [
        {
            "id": key,
            "category": "synthetic",
            "version": 1,
            "valid_from": "2026-01-01",
            "source": "test",
            "title": title,
            "answer": answer,
        }
        for key, (title, answer) in entries.items()
    ]
    return "\n".join(json.dumps(row) for row in rows) + "\n"


def synthetic_tool(tmp_path: Path, entries: dict[str, tuple[str, str]] = ENTRIES) -> SearchPolicy:
    entries_file, params_file = tmp_path / "entries.jsonl", tmp_path / "params.json"
    entries_file.write_text(entry_lines(entries))
    params_file.write_text(json.dumps(PARAMS))
    return SearchPolicy(entries_file, params_file, None)


def worded(policy: AgentPolicy, phrase: str | None = NO_MATCH_PHRASE) -> AgentPolicy:
    phrases = policy.answers.phrases
    sentences = {k: v for k, v in phrases.sentences.items() if k != "policy_no_match"}
    if phrase is not None:
        sentences["policy_no_match"] = phrase
    rules = replace(policy.answers, phrases=replace(phrases, sentences=sentences))
    return replace(policy, answers=rules)


def policy_rig(
    runner: ToolRunner,
    *outputs: str,
    phrase: str | None = NO_MATCH_PHRASE,
    answers: frozenset[str] | None = None,
    ids: frozenset[str] | None = None,
) -> tuple[Rig, SpyTool]:
    subject, spy = rig(*outputs), SpyTool(runner)
    deps = subject.deps
    known = frozenset(a for _, a in ENTRIES.values()) if answers is None else answers
    subject.deps = replace(
        deps,
        tools={**deps.tools, SEARCH: spy},
        schemas={**deps.schemas, SEARCH: SCHEMA},
        policy=worded(deps.policy, phrase),
        policy_answers=known,
        policy_ids=frozenset(ENTRIES) if ids is None else ids,
    )
    return subject, spy
