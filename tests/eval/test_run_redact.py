import json
import re

from gisting.eval.redact import DEMO_EMAIL, Redactor
from gisting.shopify.demo_email import demo_email

SECRET = "redact-test-secret-value"
KNOWN = demo_email(SECRET, "#1002")
OTHER = demo_email(SECRET, "#1003")


def test_a_known_email_goes_back_to_its_slot_name() -> None:
    redactor = Redactor({"email_a": KNOWN})
    line = json.dumps({"answer": f"sent to {KNOWN}", "raw": f"<tool_call>{KNOWN}</tool_call>"})
    redacted = redactor.apply(line)
    assert KNOWN not in redacted
    assert json.loads(redacted)["answer"] == "sent to {email_a}"
    assert redactor.unknown == 0


def test_the_match_ignores_case() -> None:
    redactor = Redactor({"email_a": KNOWN})
    assert redactor.apply(KNOWN.upper()) == "{email_a}"


def test_an_unknown_demo_email_is_replaced_and_counted() -> None:
    redactor = Redactor({"email_a": KNOWN})
    assert redactor.apply(f"{OTHER} and {KNOWN}") == "{email_unknown} and {email_a}"
    assert redactor.unknown == 1


def test_an_email_of_another_domain_is_left_alone() -> None:
    redactor = Redactor({})
    assert redactor.apply("write to ava.chen@example.com") == "write to ava.chen@example.com"


def test_a_known_email_that_is_part_of_another_is_still_matched_whole() -> None:
    redactor = Redactor({"email_a": KNOWN})
    assert redactor.apply(f"x{KNOWN}") == "x{email_a}"


def test_the_email_shape_matches_what_the_shopify_cli_prints() -> None:
    assert re.fullmatch(DEMO_EMAIL, KNOWN)
    assert re.fullmatch(DEMO_EMAIL, demo_email("another-secret", "#9999"))
