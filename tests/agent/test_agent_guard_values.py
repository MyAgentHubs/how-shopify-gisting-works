import pytest
from agent_support import rig, tool_call

from gisting.prompt.messages import UserMessage

MAIL = "ava.chen@example.com"
ASK = "Please send the missing details."


def reaches_the_tool(order: object, email: object, *texts: str) -> bool:
    subject = rig(tool_call(order_number=order, email=email), ASK)
    subject.run([UserMessage(text) for text in texts])
    return bool(subject.tool.calls)


@pytest.mark.parametrize(
    "email",
    [
        "example.com",
        "@example.com",
        "ava.chen",
        "ava.chen@example.co",
        "a",
        "@",
        " ",
        "\n",
        f" {MAIL}",
        f"{MAIL} ",
        f"{MAIL}\n",
        MAIL.upper(),
        "ava.chen@example.com.evil.net",
        "customer@example.com",
        42,
        None,
    ],
)
def test_only_a_whole_email_the_customer_wrote_reaches_the_tool(email: object) -> None:
    assert not reaches_the_tool("#1042", email, f"#1042 {MAIL}")


@pytest.mark.parametrize(
    "text",
    [
        f"#1042 {MAIL}",
        f"#1042 my email is {MAIL}.",
        f"#1042 <{MAIL}>",
        f'#1042 "{MAIL}"',
        f"#1042 ({MAIL})",
        f"#1042 [{MAIL}](mailto:{MAIL})",
        f"#1042\n{MAIL}\n",
        f"#1042\r\n{MAIL}\r\n",
        f"{MAIL}, #1042",
        f"{MAIL};1042",
        f"#1042 &lt;{MAIL}&gt;",
    ],
)
def test_an_email_written_in_ordinary_ways_is_accepted(text: str) -> None:
    assert reaches_the_tool("#1042", MAIL, text)


def test_a_decomposed_unicode_email_is_accepted_only_in_the_same_form() -> None:
    decomposed = "ju\u0308rgen@example.de"
    composed = "j\u00fcrgen@example.de"
    assert reaches_the_tool("#1042", decomposed, f"#1042 {decomposed}")
    assert not reaches_the_tool("#1042", composed, f"#1042 {decomposed}")


def test_a_non_ascii_email_is_accepted_only_exactly() -> None:
    assert reaches_the_tool("#1042", "jürgen@example.de", "#1042 jürgen@example.de")
    assert not reaches_the_tool("#1042", "jurgen@example.de", "#1042 jürgen@example.de")


def test_an_email_cannot_be_assembled_across_user_messages() -> None:
    assert not reaches_the_tool("#1042", MAIL, "#1042 ava.chen", "@example.com")
    assert not reaches_the_tool("#1042", MAIL, "#1042 ava.chen@", "example.com")
    assert not reaches_the_tool("#1042", "\n", "#1042", "hello")


def test_an_email_and_an_order_number_may_come_from_different_user_messages() -> None:
    assert reaches_the_tool("#1042", MAIL, f"my email is {MAIL}", "it is #1042")


@pytest.mark.parametrize(
    "text",
    [
        f"#1042 {MAIL}",
        f"1042 {MAIL}",
        f"order 1042. {MAIL}",
        f"No. 1042, {MAIL}",
        f"(1042) {MAIL}",
        f"is #1042 late? {MAIL}",
        f"{MAIL} 1042",
        f"order\n1042\n{MAIL}",
    ],
)
def test_an_order_number_written_on_its_own_is_accepted(text: str) -> None:
    assert reaches_the_tool("#1042", MAIL, text)
    assert reaches_the_tool("1042", MAIL, text)


@pytest.mark.parametrize(
    "text",
    [
        f"#10420 {MAIL}",
        f"#1042abc {MAIL}",
        f"1042x {MAIL}",
        f"#21042 {MAIL}",
        f"#1043 {MAIL}",
        f"#10-42 {MAIL}",
        f"#10 and 42 {MAIL}",
        f"1,042 {MAIL}",
        f"1042.0 {MAIL}",
        f"#1042.5 {MAIL}",
        f"call 555-1042 {MAIL}",
        f"on 2026-10-02 {MAIL}",
        f"on 10/42 {MAIL}",
        f"at 10:42 {MAIL}",
        f"it costs $1042 {MAIL}",
        f"I want 1042 items {MAIL}",
        f"only 10 42 {MAIL}",
        f"ava1042@example.org {MAIL}",
    ],
)
def test_digits_borrowed_from_other_context_do_not_ground_the_order_number(text: str) -> None:
    assert not reaches_the_tool("#1042", MAIL, text)


def test_digits_of_the_email_local_part_do_not_ground_the_order_number() -> None:
    assert not reaches_the_tool("#1042", "ava1042@example.com", "hello ava1042@example.com")


@pytest.mark.parametrize(
    "order",
    ["1,042", "#10-42", "1042.0", " #1042", "#1042 ", "order 1042", "#1042 #1043", "", 1042, None],
)
def test_the_order_number_argument_must_itself_be_a_plain_order_number(order: object) -> None:
    assert not reaches_the_tool(order, MAIL, f"#1042 #1043 1042 1,042 1042.0 {MAIL}")


def test_a_number_split_over_two_tokens_is_not_the_number() -> None:
    assert not reaches_the_tool("#1042", MAIL, f"#10 #42 {MAIL}")


@pytest.mark.parametrize(
    "written", ["Order #1042: has it been sent?", "#1042: where is it", "(#1042):"]
)
def test_a_hash_order_number_may_be_followed_by_a_colon(written: str) -> None:
    assert reaches_the_tool("#1042", MAIL, f"{written} {MAIL}")
    assert reaches_the_tool("1042", MAIL, f"{written} {MAIL}")


@pytest.mark.parametrize(
    "written", ["Order 1042: has it been sent?", "1042: where is it", "at 10:42"]
)
def test_a_plain_number_followed_by_a_colon_is_not_an_order_number(written: str) -> None:
    assert not reaches_the_tool("1042", MAIL, f"{written} {MAIL}")


def test_a_time_after_a_colon_is_never_read_as_an_order_number() -> None:
    assert not reaches_the_tool("30", MAIL, f"Call me at 10:30 {MAIL}")
    assert not reaches_the_tool("10", MAIL, f"Call me at 10:30 {MAIL}")
