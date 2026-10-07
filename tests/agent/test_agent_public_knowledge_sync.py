import json
import re
from pathlib import Path

from gisting.agent.public_trace import MAX_KNOWLEDGE
from gisting.kb.entries import ENTRY_ID, MAX_ID_LENGTH

ROOT = Path(__file__).resolve().parents[2]
TRACE_TS = ROOT / "apps" / "web" / "src" / "trace.ts"
SCHEMA = json.loads((ROOT / "contracts" / "public_trace.schema.json").read_text(encoding="utf-8"))
KNOWLEDGE = SCHEMA["properties"]["knowledge"]
KNOWLEDGE_ID = KNOWLEDGE["items"]["properties"]["id"]


def constant(name: str) -> str:
    found = re.search(rf"const {name} = (.+);", TRACE_TS.read_text(encoding="utf-8"))
    assert found is not None
    return found.group(1)


def test_the_web_parser_uses_the_id_grammar_of_the_knowledge_base() -> None:
    literal = re.fullmatch(r"/\^(.+)\$/u", constant("KB_ID"))
    assert literal is not None
    assert literal.group(1).replace("(?:", "(") == ENTRY_ID.pattern


def test_the_web_parser_uses_the_same_id_length_and_list_limit() -> None:
    assert int(constant("MAX_KB_ID_LENGTH")) == MAX_ID_LENGTH
    assert int(constant("MAX_KNOWLEDGE")) == MAX_KNOWLEDGE


def test_the_generated_schema_carries_the_knowledge_caps_and_the_id_grammar() -> None:
    assert KNOWLEDGE["maxItems"] == MAX_KNOWLEDGE
    assert KNOWLEDGE_ID["maxLength"] == MAX_ID_LENGTH
    assert KNOWLEDGE_ID["pattern"] == f"^{ENTRY_ID.pattern}$"


def test_the_web_parser_constants_equal_the_generated_schema() -> None:
    literal = re.fullmatch(r"/(.+)/u", constant("KB_ID"))
    assert literal is not None
    assert literal.group(1).replace("(?:", "(") == KNOWLEDGE_ID["pattern"]
    assert int(constant("MAX_KB_ID_LENGTH")) == KNOWLEDGE_ID["maxLength"]
    assert int(constant("MAX_KNOWLEDGE")) == KNOWLEDGE["maxItems"]
