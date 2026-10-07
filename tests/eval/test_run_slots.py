import pytest
from fakes.case_support import amend_many

from gisting.eval.case_spec import EvalCase
from gisting.eval.dataclass_json import decode_as
from gisting.eval.slots import SlotError, fill_case
from gisting.shopify.demo_email import demo_email

SECRET = "slot-test-secret-value"
PLAN = ["#1002", "#1003", "#1004", "#1005"]
EMAILS = {order: demo_email(SECRET, order) for order in PLAN}


def case_of(
    content: str, orders: list[tuple[str, str]], extra: list[str] | None = None
) -> EvalCase:
    messages: list[dict[str, object]] = [{"role": "user", "content": content, "tool_calls": []}]
    for index, text in enumerate(extra or []):
        role = "assistant" if index % 2 == 0 else "user"
        messages.append({"role": role, "content": text, "tool_calls": []})
    changes: dict[str, object] = {
        "messages": messages,
        "fixtures.orders": [{"order": order, "email": kind} for order, kind in orders],
    }
    return decode_as(EvalCase, amend_many(changes))


def test_a_matching_slot_becomes_the_demo_email_of_that_order() -> None:
    filled = fill_case(case_of("is {email_a} right?", [("#1003", "matching")]), PLAN, EMAILS)
    expected = demo_email(SECRET, "#1003")
    assert filled.messages[0]["content"] == f"is {expected} right?"
    assert filled.emails == {"email_a": expected}


def test_a_wrong_slot_becomes_the_email_of_another_plan_order() -> None:
    case = case_of("{email_a}", [("#1003", "wrong")])
    filled = fill_case(case, PLAN, EMAILS)
    wrong = filled.emails["email_a"]
    assert wrong != demo_email(SECRET, "#1003")
    assert wrong in {demo_email(SECRET, order) for order in PLAN}
    assert fill_case(case, PLAN, EMAILS) == filled


def test_letters_follow_the_position_of_the_order_and_wrong_never_picks_a_listed_order() -> None:
    orders = [("#1002", "matching"), ("#1003", "wrong")]
    filled = fill_case(case_of("{email_a} {email_b}", orders), PLAN, EMAILS)
    listed = {demo_email(SECRET, "#1002"), demo_email(SECRET, "#1003")}
    assert filled.emails["email_a"] == demo_email(SECRET, "#1002")
    assert filled.emails["email_b"] not in listed


def test_slots_in_every_message_are_filled() -> None:
    case = case_of("one {email_a}", [("#1002", "matching")], ["reply {email_a}", "two {email_a}"])
    contents = [message["content"] for message in fill_case(case, PLAN, EMAILS).messages]
    assert all("{" not in text for text in contents)
    assert [message["role"] for message in fill_case(case, PLAN, EMAILS).messages] == [
        "user",
        "assistant",
        "user",
    ]


def test_a_text_without_slots_is_unchanged() -> None:
    filled = fill_case(case_of("Where is #1002?", [("#1002", "absent")]), PLAN, EMAILS)
    assert filled.messages[0]["content"] == "Where is #1002?"
    assert filled.emails == {}


@pytest.mark.parametrize(
    ("content", "orders"),
    [
        ("{email_a}", []),
        ("{email_b}", [("#1002", "matching")]),
        ("{email_a}", [("#1002", "absent")]),
    ],
)
def test_a_slot_with_no_email_to_fill_is_an_error(
    content: str, orders: list[tuple[str, str]]
) -> None:
    with pytest.raises(SlotError):
        fill_case(case_of(content, orders), PLAN, EMAILS)


def test_a_message_the_agent_cannot_take_is_an_error() -> None:
    changes: dict[str, object] = {
        "messages": [
            {
                "role": "assistant",
                "content": "x",
                "tool_calls": [{"name": "lookup_order", "arguments": {}}],
            },
            {"role": "user", "content": "y", "tool_calls": []},
        ]
    }
    with pytest.raises(SlotError):
        fill_case(decode_as(EvalCase, amend_many(changes)), PLAN, EMAILS)
