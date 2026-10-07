import json
import re
from pathlib import Path

import pytest

from gisting.eval.contamination import (
    Hit,
    Policy,
    Text,
    contaminated,
    load_policy,
    string_leaves,
    tokens_of,
    training_family_names,
    training_texts,
)
from gisting.shopify.jsonvalue import Json

POLICY_FILE = Path(__file__).resolve().parents[2] / "data" / "eval" / "contamination-v1.json"
POLICY = Policy(
    ngram_words=4,
    min_words=2,
    max_shared_ngrams=0,
    slots=(re.compile(r"\{[a-z_]+\}"), re.compile(r"#?\d{3,}"), re.compile(r"\S+@\S+")),
)


def text(label: str, body: str) -> Text:
    return Text(label, tokens_of(body, POLICY))


def test_the_committed_policy_loads_with_the_documented_defaults() -> None:
    policy = load_policy(POLICY_FILE)
    assert (policy.ngram_words, policy.min_words, policy.max_shared_ngrams) == (8, 4, 0)
    assert policy.slots


def test_a_policy_with_a_bad_pattern_or_missing_key_is_rejected(tmp_path: Path) -> None:
    bad = tmp_path / "policy.json"
    bad.write_text(json.dumps({"version": 1, "ngram_words": 8, "slots": ["("]}), encoding="utf-8")
    with pytest.raises(ValueError, match="policy"):
        load_policy(bad)


def test_slots_make_templates_and_concrete_values_comparable() -> None:
    template = tokens_of("Where is my order {order}? Email {email}", POLICY)
    concrete = tokens_of("where is my order #1042? email ava@example.com", POLICY)
    assert template == concrete


def test_a_shared_long_phrase_is_flagged_with_its_count() -> None:
    reference = [text("ref", "please tell me where my parcel is right now")]
    candidate = [text("case", "hey please tell me where my parcel is")]
    assert contaminated(candidate, reference, POLICY) == [Hit("case", "ref", 4)]


def test_unrelated_texts_are_clean() -> None:
    reference = [text("ref", "please tell me where my parcel is right now")]
    candidate = [text("case", "write a poem about the sea and the sky")]
    assert contaminated(candidate, reference, POLICY) == []


def test_the_threshold_allows_a_configured_amount_of_overlap() -> None:
    relaxed = Policy(4, 2, 4, POLICY.slots)
    reference = [text("ref", "please tell me where my parcel is right now")]
    candidate = [text("case", "hey please tell me where my parcel is")]
    assert contaminated(candidate, reference, relaxed) == []


def test_a_short_text_inside_a_longer_reference_is_flagged() -> None:
    reference = [text("ref", "hello there where is my order {order} today")]
    assert contaminated([text("case", "where is my order")], reference, POLICY) == [
        Hit("case", "ref", 1)
    ]


def test_texts_under_the_minimum_length_are_exempt() -> None:
    reference = [text("ref", "no thanks that is all")]
    assert contaminated([text("case", "no")], reference, POLICY) == []


def test_string_leaves_walks_nested_documents() -> None:
    document: Json = {"a": ["x", {"b": "y"}], "n": 1}
    assert list(string_leaves(document, "")) == [("a[0]", "x"), ("a[1].b", "y")]


def test_training_texts_cover_every_string_in_the_templates_document() -> None:
    document: Json = {"fam": {"split": "train", "templates": ["Where is {order} please now"]}}
    labels = [item.label for item in training_texts(document, POLICY)]
    assert "fam.templates[0]" in labels


def test_training_family_names_are_the_keys_that_own_templates() -> None:
    document: Json = {
        "first": {"families": {"eta": {"split": "dev", "templates": ["a"]}}},
        "x": {"y": 1},
    }
    assert training_family_names(document) == frozenset({"eta"})
