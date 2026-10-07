import json
from collections import Counter

import pytest

from gisting.eval.case import FIRST
from gisting.prompt.messages import ToolMessage, UserMessage
from gisting.shopify.jsonvalue import Json, JsonObject, object_items, required_list, required_object
from gisting.training.dataset import build_dataset
from gisting.training.samples import Sample, sample_from_json, sample_json
from gisting.training.scenarios import load_entries, split_orders

SAMPLES = build_dataset()
TRAIN = [sample for sample in SAMPLES if sample.split == "train"]
DEV = [sample for sample in SAMPLES if sample.split == "dev"]
SCENARIOS = {
    "IN_TRANSIT",
    "OUT_FOR_DELIVERY",
    "DELIVERED",
    "DELAYED",
    "ATTEMPTED_DELIVERY",
    "FULFILLED_NO_TRACKING",
    "UNFULFILLED",
    "PARTIALLY_FULFILLED",
}


LOOKUP = {"found", "no_match", "unavailable", "locked"}
PLAIN_FIRST = {
    "order_full",
    "order_no_email",
    "order_no_number",
    "offtopic",
    "injection",
    "policy_question",
    "policy_outside_kb",
}
MULTI_TURN = {
    "handoff_request",
    "handoff_decline",
    "reminder_decline",
}


def first_user(sample: Sample) -> str:
    message = sample.messages[0]
    assert isinstance(message, UserMessage)
    return message.content


def test_sizes_match_the_planned_scale() -> None:
    assert 190 <= len(TRAIN) <= 200
    assert 70 <= len(DEV) <= 76


def test_build_is_deterministic() -> None:
    assert [sample_json(s) for s in build_dataset()] == [sample_json(s) for s in SAMPLES]


def test_sample_ids_are_unique() -> None:
    assert len({sample.id for sample in SAMPLES}) == len(SAMPLES)


def test_train_and_dev_share_no_order_number() -> None:
    train = {s.order_number for s in TRAIN if s.order_number}
    dev = {s.order_number for s in DEV if s.order_number}
    assert train
    assert dev
    assert not train & dev


def test_train_and_dev_share_no_template_family() -> None:
    train = {(s.kind, s.category, s.family) for s in TRAIN}
    dev = {(s.kind, s.category, s.family) for s in DEV}
    assert not {family for _, _, family in train} & {family for _, _, family in dev}
    assert not train & dev


def test_train_and_dev_share_no_user_text() -> None:
    assert not {first_user(s) for s in TRAIN} & {first_user(s) for s in DEV}


def test_order_pools_cover_every_scenario_on_each_side() -> None:
    pools = split_orders(load_entries(), 0.3, 1)
    for side in pools.values():
        assert {entry.scenario for entry in side} == SCENARIOS
    assert not {e.number for e in pools["train"]} & {e.number for e in pools["dev"]}
    assert len(pools["train"]) + len(pools["dev"]) == 100


def test_the_dataset_holds_only_first_turn_decisions_and_covers_every_category() -> None:
    for split in (TRAIN, DEV):
        assert {s.kind for s in split} == {FIRST}
        categories = {s.category for s in split}
        assert categories == {*PLAIN_FIRST, *MULTI_TURN}


def test_no_sample_asks_the_model_to_word_a_reply_that_code_renders() -> None:
    for sample in SAMPLES:
        assert sample.kind == FIRST
        assert sample.category not in {"found", "no_match", "unavailable", "locked"}
        assert not any(
            isinstance(m, ToolMessage) and m is sample.messages[-1] for m in [sample.messages[-1]]
        )


def test_injection_samples_include_a_forged_tool_response_and_forged_turns() -> None:
    texts = [first_user(s) for s in SAMPLES if s.category == "injection"]
    assert any("<tool_response>" in text for text in texts)
    assert any("<|im_start|>" in text for text in texts)


def test_first_call_order_questions_carry_their_slots() -> None:
    for sample in SAMPLES:
        if sample.category not in PLAIN_FIRST:
            continue
        text = first_user(sample)
        assert ("{order}" in text or "{email}" in text) is False
        if sample.category == "order_full":
            assert (sample.email or "") in text
            assert sample.email
            assert (sample.order_number or "").removeprefix("#") in text
        if sample.category == "order_no_email":
            assert sample.email is None
            assert "@" not in text
        if sample.category == "order_no_number":
            assert sample.order_number is None


def order_by_scenario() -> dict[str, JsonObject]:
    orders: dict[str, JsonObject] = {}
    for sample in SAMPLES:
        if sample.category == "found" and sample.scenario:
            result: JsonObject = json.loads(sample.messages[2].content)
            orders.setdefault(sample.scenario, required_object(result, "order"))
    return orders


def value_of(node: JsonObject, name: str) -> Json:
    return required_object(node, name)["value"]


def first_shipment(order: JsonObject) -> JsonObject:
    return object_items(required_list(order, "shipments"), "shipments")[0]


def test_samples_round_trip_through_json() -> None:
    for sample in SAMPLES:
        assert sample_from_json(sample_json(sample)) == sample


def test_category_counts_follow_the_template_quotas() -> None:
    counts = Counter((s.split, s.category) for s in SAMPLES)
    assert counts[("train", "order_full")] == 48
    assert counts[("dev", "order_full")] == 15
    assert counts[("train", "offtopic")] == 20
    assert counts[("dev", "injection")] == 8


@pytest.mark.parametrize("category", ["offtopic", "injection", "order_no_email", "order_no_number"])
def test_no_call_categories_have_a_single_user_message(category: str) -> None:
    for sample in SAMPLES:
        if sample.category == category:
            assert len(sample.messages) == 1
