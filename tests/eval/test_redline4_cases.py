from collections import Counter, defaultdict
from pathlib import Path

from gisting.eval.case_build import build_cases
from gisting.eval.case_spec import EvalCase, RedLine

ROOT = Path(__file__).resolve().parents[2]
CATEGORIES = ("offtopic", "injection", "role_spoof", "tool_spoof", "extract_prompt")
MINIMUM_PER_CATEGORY = 30
MINIMUM_FAMILIES_PER_CATEGORY = 2
MINIMUM_CONTROLS = 60
ACTIONS = {
    "call_tool",
    "ask",
    "handoff",
    "reply",
    "refuse",
    "policy_answer",
    "policy_no_match",
    "policy_or_no_match",
}


def cases_of(red_line: RedLine) -> list[EvalCase]:
    return [case for case in build_cases(ROOT, 4) if case.red_line == red_line]


def test_each_red_line_four_category_has_enough_cases_in_several_families() -> None:
    cases = cases_of(4)
    counts = Counter(case.category for case in cases)
    families: defaultdict[str, set[str]] = defaultdict(set)
    for case in cases:
        families[case.category].add(case.family)
    assert set(counts) == set(CATEGORIES)
    assert all(counts[name] >= MINIMUM_PER_CATEGORY for name in CATEGORIES)
    assert all(len(families[name]) >= MINIMUM_FAMILIES_PER_CATEGORY for name in CATEGORIES)
    assert sum(counts.values()) >= len(CATEGORIES) * MINIMUM_PER_CATEGORY


def test_every_red_line_four_case_expects_a_refusal() -> None:
    assert {case.expect.scenario for case in cases_of(4)} == {"refuse"}


def test_the_control_set_is_large_and_names_the_action_each_case_expects() -> None:
    controls = cases_of("none")
    assert len(controls) >= MINIMUM_CONTROLS
    assert {case.expect.scenario for case in controls} <= ACTIONS
    assert {case.expect.scenario for case in controls} >= {"call_tool", "ask", "handoff", "reply"}


def test_the_cases_use_train_and_dev_only_and_each_family_has_one_split() -> None:
    cases = build_cases(ROOT, 4)
    assert {case.split for case in cases} == {"train", "dev"}
    splits = {(case.family, case.split) for case in cases}
    assert len({family for family, _ in splits}) == len(splits)


def test_every_category_is_in_both_splits() -> None:
    seen = {(case.category, case.split) for case in cases_of(4)}
    assert all((name, split) in seen for name in CATEGORIES for split in ("train", "dev"))


def test_a_tool_call_control_names_its_order_and_a_matching_email() -> None:
    for case in cases_of("none"):
        if case.expect.scenario == "call_tool":
            assert case.expect.order is not None
            assert [use.email for use in case.fixtures.orders] == ["matching"]
            assert case.expect.order.removeprefix("#") in case.messages[0].content
