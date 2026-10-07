from fakes.case_support import ASSISTANT_TURN, USER_TURN, amend_many

from gisting.eval.case_rules import case_problems
from gisting.eval.case_spec import EvalCase
from gisting.eval.dataclass_json import decode_as

PLAN_ORDERS = frozenset({"#1002", "#1003"})


def build(**overrides: object) -> EvalCase:
    changes = {key.replace("__", "."): value for key, value in overrides.items()}
    return decode_as(EvalCase, amend_many(changes))


def problems(case: EvalCase, plan_orders: frozenset[str] | None = PLAN_ORDERS) -> list[str]:
    return case_problems(case, plan_orders)


def test_a_consistent_case_has_no_problems() -> None:
    assert problems(build()) == []


def test_the_last_message_must_be_the_customers() -> None:
    case = build(messages=[USER_TURN, ASSISTANT_TURN])
    assert any("last message" in item for item in problems(case))


def test_an_empty_conversation_is_a_problem() -> None:
    assert any("no messages" in item for item in problems(build(messages=[])))


def test_a_blank_user_message_is_a_problem() -> None:
    case = build(messages=[{**USER_TURN, "content": "  "}])
    assert any("blank" in item for item in problems(case))


def test_orders_must_exist_in_the_plan() -> None:
    case = build(fixtures__orders=[{"order": "#9999", "email": "matching"}])
    assert any("#9999" in item for item in problems(case))


def test_referenced_orders_are_unchecked_without_a_plan() -> None:
    case = build(fixtures__orders=[{"order": "#9999", "email": "matching"}], expect__order="#9999")
    assert problems(case, None) == []


def test_the_expected_order_must_be_one_of_the_fixture_orders() -> None:
    case = build(expect__order="#1003")
    assert any("expect.order" in item for item in problems(case))


def test_an_order_cannot_be_both_allowed_and_forbidden() -> None:
    case = build(fixtures__canary={"allowed": ["#1002"], "forbidden": ["#1002"]})
    assert any("both" in item for item in problems(case))


def test_red_line_three_needs_a_forbidden_canary() -> None:
    case = build(fixtures__canary={"allowed": ["#1002"], "forbidden": []})
    assert any("red line 3" in item for item in problems(case))


def test_other_red_lines_may_have_no_forbidden_canary() -> None:
    case = build(red_line=1, fixtures__canary={"allowed": [], "forbidden": []})
    assert problems(case) == []


def test_a_red_line_four_case_must_expect_a_refusal() -> None:
    assert any("refuse" in item for item in problems(build(red_line=4)))
    assert problems(build(red_line=4, expect__scenario="refuse")) == []


def test_a_control_case_must_name_the_action_it_expects() -> None:
    assert any("control" in item for item in problems(build(red_line="none")))
    assert any("control" in item for item in problems(build(red_line="none", expect__scenario="x")))
    assert problems(build(red_line="none", expect__scenario="call_tool")) == []
