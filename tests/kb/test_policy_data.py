import json
import re
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
POLICY_FILE = REPO / "kb" / "policy-v1.jsonl"
FIELDS = {"id", "category", "version", "valid_from", "source", "title", "answer"}
SLUG = re.compile(r"^[a-z]+(-[a-z]+)*$")
ENTRY_COUNT = 38


def rows() -> list[dict[str, object]]:
    lines = POLICY_FILE.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines]


def test_the_approved_set_has_thirty_eight_entries() -> None:
    assert len(rows()) == ENTRY_COUNT


def test_every_entry_has_exactly_the_required_fields() -> None:
    assert all(set(row) == FIELDS for row in rows())


def test_ids_are_unique_and_prefixed() -> None:
    ids = [str(row["id"]) for row in rows()]
    assert len(set(ids)) == len(ids)
    assert all(re.fullmatch(r"kb-[a-z]+(-[a-z]+)*", entry) for entry in ids)


def test_categories_are_lowercase_hyphen_slugs() -> None:
    assert all(SLUG.fullmatch(str(row["category"])) for row in rows())


def test_versions_are_positive_integers_and_dates_parse() -> None:
    for row in rows():
        assert isinstance(row["version"], int)
        assert row["version"] >= 1
        assert date.fromisoformat(str(row["valid_from"])).isoformat() == row["valid_from"]


def test_text_fields_are_non_empty_trimmed_strings() -> None:
    for row in rows():
        for name in ("source", "title", "answer"):
            value = row[name]
            assert isinstance(value, str)
            assert value
            assert value == value.strip()
