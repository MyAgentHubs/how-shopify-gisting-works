import json
from pathlib import Path

import pytest
from fakes.shopify import FakeOrder
from tool_support import POLICY, obj_at, state_of

from gisting.shopify.jsonvalue import Json, JsonObject
from gisting.tools.attempts import InMemoryFailureCounter
from gisting.tools.cache import InMemoryOrderCache
from gisting.tools.facts import FIELD_NAMES, Source, canary_of
from gisting.tools.policy import POLICY_FILE, PolicyError, load_policy
from gisting.tools.verification import email_matches, in_range, parse_order_name


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_cache_entries_expire_after_the_ttl() -> None:
    clock = Clock()
    cache = InMemoryOrderCache(30, clock)
    cache.put("#1042", state_of(FakeOrder(1042)))
    clock.now = 29.9
    assert cache.get("#1042") is not None
    clock.now = 30
    assert cache.get("#1042") is None
    assert cache.get("#1043") is None


def test_failures_are_counted_per_session() -> None:
    counter = InMemoryFailureCounter(limit=5)
    counter.record_failure("a")
    counter.record_failure("a")
    assert (counter.failures("a"), counter.failures("b")) == (2, 0)


def test_counter_locks_a_session_at_its_own_limit_and_only_that_session() -> None:
    counter = InMemoryFailureCounter(limit=2)
    counter.record_failure("a")
    assert not counter.is_locked("a")
    counter.record_failure("a")
    counter.record_failure("b")
    assert (counter.is_locked("a"), counter.is_locked("b")) == (True, False)


def test_real_policy_covers_every_field_and_the_demo_range() -> None:
    assert (POLICY.order_min, POLICY.order_max) == (1001, 1101)
    assert POLICY.failure_limit >= 1
    assert set(POLICY.sources) == set(FIELD_NAMES)
    assert {POLICY.sources[name] for name in FIELD_NAMES} == {Source.SHOPIFY, Source.SIMULATED}


def test_policy_with_a_missing_field_source_is_rejected(tmp_path: Path) -> None:
    document = policy_document()
    del obj_at(document, "field_sources")["carrier"]
    with pytest.raises(PolicyError):
        load_policy(write_policy(tmp_path, document))


def policy_document() -> JsonObject:
    document: Json = json.loads(POLICY_FILE.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def write_policy(tmp_path: Path, document: JsonObject) -> Path:
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(document))
    return path


def test_policy_with_an_unknown_source_is_rejected(tmp_path: Path) -> None:
    document = policy_document()
    obj_at(document, "field_sources")["carrier"] = "guessed"
    with pytest.raises(PolicyError):
        load_policy(write_policy(tmp_path, document))


def test_policy_with_inverted_range_is_rejected(tmp_path: Path) -> None:
    document = policy_document()
    obj_at(document, "order_range")["min"] = 2000
    with pytest.raises(PolicyError):
        load_policy(write_policy(tmp_path, document))


def test_policy_with_zero_failure_limit_is_rejected(tmp_path: Path) -> None:
    document = policy_document()
    document["failure_limit_per_session"] = 0
    with pytest.raises(PolicyError):
        load_policy(write_policy(tmp_path, document))


def test_missing_policy_file_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(PolicyError):
        load_policy(tmp_path / "missing.json")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("#1042", "#1042"), ("1042", "#1042"), (" 01042 ", "#1042"), ("#1001", "#1001")],
)
def test_order_names_are_normalised(raw: str, expected: str) -> None:
    assert parse_order_name(raw) == expected


@pytest.mark.parametrize("raw", ["", "#", "x1042", "10 42", "١٠٤٢", "1042.0", "-1042", "1" * 13])
def test_malformed_order_names_are_rejected(raw: str) -> None:
    assert not isinstance(parse_order_name(raw), str)


def test_range_check_is_inclusive() -> None:
    assert [in_range(name, POLICY) for name in ("#1000", "#1001", "#1101", "#1102")] == [
        False,
        True,
        True,
        False,
    ]


def test_email_comparison_is_exact_and_survives_lone_surrogates() -> None:
    assert email_matches("a@b.c", "a@b.c")
    assert not email_matches("a@b.c", "A@b.c")
    assert not email_matches("a@b.c", "a@b.c ")
    assert not email_matches("a@b.c", "\ud800")


def test_canary_is_read_from_the_order_note() -> None:
    assert canary_of("Test order. Reference GLR-DC26C5A7") == "GLR-DC26C5A7"
    assert canary_of("no marker") is None
    assert canary_of(None) is None
