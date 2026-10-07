import hashlib
import json
import re
from collections import Counter
from pathlib import Path

from gisting.prompt.messages import UserMessage
from gisting.training.dataset import build_dataset
from gisting.training.samples import Sample, dump_jsonl, sample_json

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = build_dataset()
POLICY_ID = re.compile(r"-p\d{3}$")
POLICY_SAMPLES = [s for s in SAMPLES if POLICY_ID.search(s.id)]
EXISTING_SHA256 = "43d47c869d28d99b3811c4fc6a8fd85c19e228f65bad1e01ae78d60d936f300f"
NEW_COUNTS = {
    ("train", "policy_question"): 31,
    ("dev", "policy_question"): 15,
    ("train", "policy_outside_kb"): 10,
    ("dev", "policy_outside_kb"): 5,
    ("train", "order_full"): 8,
    ("dev", "order_full"): 3,
    ("train", "order_no_email"): 6,
    ("dev", "order_no_email"): 3,
}


def first_text(sample: Sample) -> str:
    message = sample.messages[0]
    assert isinstance(message, UserMessage)
    return message.content


def jsonl(path: str) -> list[dict[str, str]]:
    lines = (ROOT / path).read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def test_the_rows_that_existed_before_the_policy_categories_are_byte_identical() -> None:
    old = [sample_json(s) for s in SAMPLES if s not in POLICY_SAMPLES]
    assert hashlib.sha256(dump_jsonl(old).encode()).hexdigest() == EXISTING_SHA256


def test_policy_samples_are_added_per_split_and_category_by_the_quota() -> None:
    assert Counter((s.split, s.category) for s in POLICY_SAMPLES) == NEW_COUNTS


def test_policy_ids_are_unique_and_built_from_split_and_category() -> None:
    assert len({s.id for s in SAMPLES}) == len(SAMPLES)
    for sample in POLICY_SAMPLES:
        assert sample.id.startswith(f"{sample.split}-first-{sample.category}-p")


def test_policy_question_covers_every_knowledge_base_category_in_both_splits() -> None:
    wanted = {row["category"].replace("-", "_") for row in jsonl("kb/policy-v1.jsonl")}
    assert len(wanted) == 13
    for split in ("train", "dev"):
        seen = {
            s.family.removeprefix("dev_").removeprefix("question_")
            for s in POLICY_SAMPLES
            if s.category == "policy_question" and s.split == split
        }
        assert seen == wanted


def test_questions_without_an_order_carry_no_order_number_or_email() -> None:
    for sample in POLICY_SAMPLES:
        if sample.category in ("policy_question", "policy_outside_kb"):
            assert len(sample.messages) == 1
            assert sample.order_number is None
            assert sample.email is None
            assert "@" not in first_text(sample)
            assert not re.search(r"\d{3}|\{", first_text(sample))


def test_policy_questions_about_an_order_follow_the_order_flow_slots() -> None:
    for sample in POLICY_SAMPLES:
        text = first_text(sample)
        if sample.category == "order_full":
            assert sample.email
            assert sample.email in text
            assert (sample.order_number or "").removeprefix("#") in text
        if sample.category == "order_no_email":
            assert sample.email is None
            assert "@" not in text
            assert (sample.order_number or "").removeprefix("#") in text


def test_policy_samples_share_no_user_text_or_template_family_across_splits() -> None:
    train = [s for s in POLICY_SAMPLES if s.split == "train"]
    dev = [s for s in POLICY_SAMPLES if s.split == "dev"]
    assert not {first_text(s) for s in train} & {first_text(s) for s in dev}
    assert not {s.family for s in train} & {s.family for s in dev}
    assert not {s.order_number for s in train if s.order_number} & {
        s.order_number for s in dev if s.order_number
    }


def test_every_policy_template_is_used_once_so_the_quota_matches_the_pool() -> None:
    texts = [first_text(s) for s in POLICY_SAMPLES if s.category == "policy_question"]
    assert len(texts) == len(set(texts))


def test_no_policy_template_copies_a_retrieval_query_or_a_knowledge_base_title() -> None:
    borrowed = {row["query"].casefold() for row in jsonl("kb/queries-v1.jsonl")}
    borrowed |= {row["title"].casefold() for row in jsonl("kb/policy-v1.jsonl")}
    for sample in POLICY_SAMPLES:
        assert first_text(sample).casefold() not in borrowed
