import json
import re
from collections import Counter
from pathlib import Path

import pytest

from gisting.eval.case_build import TemplateError, build_cases
from gisting.eval.case_files import plan_orders
from gisting.eval.case_spec import EvalCase

ROOT = Path(__file__).resolve().parents[2]
PLAN_FILE = "shipment-plan-v1.json"
PLAN = {entry.order: entry for entry in plan_orders(ROOT, PLAN_FILE) or []}
CASES = build_cases(ROOT, 1)
MINIMUM_CASES = 300
STATUSES = {
    "IN_TRANSIT",
    "OUT_FOR_DELIVERY",
    "DELAYED",
    "ATTEMPTED_DELIVERY",
    "DELIVERED",
    "FULFILLED_NO_TRACKING",
    "UNFULFILLED",
    "PARTIALLY_FULFILLED",
}
CATEGORIES = {
    "status_lookup",
    "follow_up",
    "no_order",
    "customer_date",
    "order_switch",
    "retry_date",
    "policy_question",
    "policy_after_order",
    "order_after_policy",
}
NO_ORDER_CATEGORIES = {"no_order", "policy_question"}


def of(category: str) -> list[EvalCase]:
    return [case for case in CASES if case.category == category]


def sandbox(tmp_path: Path, family: dict[str, object]) -> Path:
    base: dict[str, object] = {
        "split": "dev",
        "category": "probe",
        "scenario": "probe",
        "orders": [{"letter": "a", "email": "matching"}],
        "allowed": ["a"],
        "forbidden": [],
        "expect_order": "a",
    }
    document = {
        "version": 1,
        "seed": 1,
        "red_line": 1,
        "plan": PLAN_FILE,
        "families": {"probe_family": base | family},
    }
    (tmp_path / "data" / "eval").mkdir(parents=True)
    (tmp_path / "data" / "demo-orders").mkdir(parents=True)
    (tmp_path / "data" / "eval" / "redline12-templates.json").write_text(json.dumps(document))
    plan = ROOT / "data" / "demo-orders" / PLAN_FILE
    (tmp_path / "data" / "demo-orders" / PLAN_FILE).write_text(plan.read_text(encoding="utf-8"))
    return tmp_path


def test_there_are_enough_cases_in_train_and_dev_only() -> None:
    assert len(CASES) >= MINIMUM_CASES
    assert {case.split for case in CASES} == {"train", "dev"}
    assert {case.red_line for case in CASES} == {1}
    assert {case.category for case in CASES} == CATEGORIES


def test_each_family_lives_in_one_split_and_each_category_is_in_both() -> None:
    splits = {(case.family, case.split) for case in CASES}
    assert len({family for family, _ in splits}) == len(splits)
    assert {(case.category, case.split) for case in CASES} == {
        (name, split) for name in CATEGORIES for split in ("train", "dev")
    }


def test_every_plan_status_is_asked_about_in_both_splits() -> None:
    seen = {
        (PLAN[case.expect.order].scenario, case.split)
        for case in of("status_lookup")
        if case.expect.order
    }
    assert seen == {(status, split) for status in STATUSES for split in ("train", "dev")}


def test_a_status_case_names_its_plan_status_as_scenario() -> None:
    for case in of("status_lookup"):
        assert case.expect.order is not None
        assert PLAN[case.expect.order].scenario.lower() == case.expect.scenario


def test_an_order_case_authorises_the_order_it_expects_with_a_matching_email() -> None:
    for case in CASES:
        if case.category in NO_ORDER_CATEGORIES:
            continue
        assert case.expect.order is not None, case.id
        assert case.expect.order in case.fixtures.canary.allowed, case.id
        assert all(use.email == "matching" for use in case.fixtures.orders), case.id
        assert case.expect.order in PLAN, case.id


def test_a_case_without_an_order_names_none_and_writes_no_order_number() -> None:
    cases = of("no_order")
    assert len(cases) >= 50
    for case in cases:
        assert case.fixtures.orders == ()
        assert case.expect.order is None
        assert case.fixtures.canary.allowed == ()
        assert not re.search(r"#?\d{3,}", case.messages[0].content)


def test_a_follow_up_replays_the_looked_up_order_in_the_earlier_assistant_reply() -> None:
    cases = of("follow_up")
    assert len(cases) >= 90
    for case in cases:
        roles = [message.role for message in case.messages]
        assert roles == ["user", "assistant", "user"], case.id
        assert case.expect.order is not None
        reply = case.messages[1].content
        assert case.expect.order in reply
        tracking = PLAN[case.expect.order].tracking
        if tracking:
            assert tracking in reply


def test_a_customer_date_case_gives_a_date_in_the_message() -> None:
    month = r"(?:sep|oct)|\d{1,2}/\d{1,2}|2026-\d\d-\d\d"
    for case in of("customer_date"):
        assert re.search(month, case.messages[0].content, re.IGNORECASE), case.id


def test_a_switch_case_expects_the_second_order_and_authorises_both() -> None:
    cases = of("order_switch")
    assert len(cases) >= 20
    for case in cases:
        first, second = (use.order for use in case.fixtures.orders)
        assert first != second
        assert case.expect.order == second
        assert set(case.fixtures.canary.allowed) == {first, second}
        assert second in case.messages[-1].content
        assert first in case.messages[0].content


def test_a_retry_case_uses_a_delayed_or_attempted_order() -> None:
    for case in of("retry_date"):
        assert case.expect.order is not None
        assert PLAN[case.expect.order].scenario in {"DELAYED", "ATTEMPTED_DELIVERY"}


def test_only_email_slots_are_left_for_the_runner() -> None:
    for case in CASES:
        text = " ".join(message.content for message in case.messages)
        assert not re.search(r"\{(?!email_)[a-z]+_[a-z]\}", text), case.id


def test_case_ids_are_unique() -> None:
    counts = Counter(case.id for case in CASES)
    assert max(counts.values()) == 1


def test_a_carrier_slot_for_an_order_without_tracking_is_refused(tmp_path: Path) -> None:
    root = sandbox(
        tmp_path,
        {
            "orders": [{"letter": "a", "email": "matching", "scenarios": ["UNFULFILLED"]}],
            "templates": [[{"role": "user", "content": "Carrier of {order_a} is {carrier_a}?"}]],
        },
    )
    with pytest.raises(TemplateError, match="unfilled slot"):
        build_cases(root, 1)


def test_an_empty_scenario_pool_is_refused(tmp_path: Path) -> None:
    root = sandbox(
        tmp_path,
        {
            "orders": [{"letter": "a", "email": "matching", "scenarios": ["NO_SUCH_STATUS"]}],
            "templates": [[{"role": "user", "content": "Where is {order_a}?"}]],
        },
    )
    with pytest.raises(TemplateError, match="no plan order left"):
        build_cases(root, 1)


def test_two_letters_in_one_case_get_different_orders(tmp_path: Path) -> None:
    root = sandbox(
        tmp_path,
        {
            "orders": [
                {"letter": "a", "email": "matching", "scenarios": ["DELAYED"]},
                {"letter": "b", "email": "matching", "scenarios": ["DELAYED"]},
            ],
            "allowed": ["a", "b"],
            "expect_order": "b",
            "templates": [[{"role": "user", "content": "{order_a} then {order_b}"}]] * 6,
        },
    )
    for case in build_cases(root, 1):
        first, second = (use.order for use in case.fixtures.orders)
        assert first != second
