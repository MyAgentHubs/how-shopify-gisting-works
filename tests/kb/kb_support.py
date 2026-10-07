from gisting.kb.aliases import load_aliases
from gisting.kb.bm25 import Index, build_index
from gisting.kb.entries import Entry, load_entries
from gisting.kb.params import Bm25Params, load_params

PARAMS = Bm25Params(k1=1.5, b=0.75, default_top_k=3, max_top_k=10)


def entry(entry_id: str, text: str) -> Entry:
    return Entry(
        id=entry_id,
        category="synthetic",
        version=1,
        valid_from="2026-01-01",
        source="test",
        title="t",
        answer=text,
    )


def index_of(*pairs: tuple[str, str], params: Bm25Params = PARAMS) -> Index:
    return build_index(tuple(entry(entry_id, text) for entry_id, text in pairs), params)


def real_index() -> Index:
    entries = load_entries()
    return build_index(entries, load_params(), load_aliases(entries))
