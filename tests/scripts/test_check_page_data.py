import json
import re
import shutil
from collections.abc import Callable
from pathlib import Path

import pytest
from conftest import SCRIPTS_DIR, Guard

from gisting.shopify.demo_email import demo_email
from gisting.shopify.jsonvalue import Json, JsonObject, object_items, required_list, required_object

REPO = SCRIPTS_DIR.parent
SCRIPT = "check_page_data.py"
PRICING = "apps/web/data/pricing.json"
EXAMPLES = "apps/web/data/example_orders.json"
PUBLIC_ORDERS = "apps/web/data/public_orders.json"
PIN = "apps/web/data/public_orders_pin.json"
RUNTIME = "apps/web/data/runtime.json"
PLAN = "data/demo-orders/shipment-plan-v1.json"
RELEASE_LOCK = "apps/web/data/release_lock.json"
REAL_EMAIL = "abcdefghij@orders.example.com"
PLACEHOLDER_EMAIL = "xxxxxxxxxx@orders.example.com"
TEST_SITEKEY = "1x00000000000000000000AA"
SECRET_LIKE = "0x4AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"

Edit = Callable[[JsonObject], object]


@pytest.fixture
def root(tmp_path: Path) -> Path:
    for relative in (PRICING, EXAMPLES, PUBLIC_ORDERS, PIN, RUNTIME, PLAN, RELEASE_LOCK):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO / relative, target)
    return tmp_path


def edit(root: Path, relative: str, change: Edit) -> None:
    path = root / relative
    document: Json = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    change(document)
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def rows(document: JsonObject) -> list[JsonObject]:
    return object_items(required_list(document, "examples"), "examples")


def turnstile(document: JsonObject) -> JsonObject:
    return required_object(document, "turnstile")


def set_plan_scenario(order: str, scenario: str) -> Edit:
    def change(document: JsonObject) -> None:
        for entry in object_items(required_list(document, "entries"), "entries"):
            if entry["order"] == order:
                entry["scenario"] = scenario

    return change


def fail_with(guard: Guard, root: Path, relative: str, fragment: str) -> None:
    result = guard(SCRIPT, root)
    assert result.returncode == 1, result.stderr
    assert any(
        line.startswith(f"{relative}:1:") and fragment in line
        for line in result.stderr.splitlines()
    ), result.stderr


def sync_public_emails(root: Path) -> None:
    document: Json = json.loads((root / EXAMPLES).read_text())
    assert isinstance(document, dict)
    emails = {str(row["order"]): row["email"] for row in rows(document) if "order" in row}

    def change(public: JsonObject) -> None:
        for row in object_items(required_list(public, "orders"), "orders"):
            if str(row["order"]) in emails:
                row["email"] = emails[str(row["order"])]

    edit(root, PUBLIC_ORDERS, change)


def placeholder_root(root: Path) -> Path:
    def emails(document: JsonObject) -> None:
        for index, row in enumerate(rows(document)):
            if "email" in row:
                row["email"] = PLACEHOLDER_EMAIL if index == 0 else "yyyyyyyyyy@orders.example.com"

    edit(root, EXAMPLES, emails)
    sync_public_emails(root)
    edit(root, RUNTIME, lambda document: turnstile(document).update(sitekey=TEST_SITEKEY))
    return root


@pytest.mark.parametrize("flags", [(), ("--strict",)])
def test_the_committed_data_passes_without_notes(flags: tuple[str, ...], guard: Guard) -> None:
    result = guard(SCRIPT, REPO, *flags)
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")


def test_placeholders_in_a_fixture_are_only_notes(root: Path, guard: Guard) -> None:
    result = guard(SCRIPT, placeholder_root(root))
    assert result.returncode == 0
    lines = result.stderr.splitlines()
    assert len(lines) == 5
    assert all(line.startswith("note: ") and "the release lock blocks it" in line for line in lines)
    assert "#1006" in lines[0]
    assert "#1022" in lines[1]
    assert "sitekey" in lines[-1]


def test_strict_turns_the_placeholders_in_a_fixture_into_failures(root: Path, guard: Guard) -> None:
    result = guard(SCRIPT, placeholder_root(root), "--strict")
    assert result.returncode == 1
    assert "example_orders.json:1: the email of #1006 is still the placeholder" in result.stderr
    assert "example_orders.json:1: the email of #1022 is still the placeholder" in result.stderr
    assert "runtime.json:1: the sitekey is still a Cloudflare test key" in result.stderr


def test_real_looking_values_pass_strict_without_notes(root: Path, guard: Guard) -> None:
    def emails(document: JsonObject) -> None:
        for row in rows(document):
            if "email" in row:
                row["email"] = demo_email("unit-test-secret", str(row["order"]))

    edit(root, EXAMPLES, emails)
    sync_public_emails(root)
    edit(
        root,
        RUNTIME,
        lambda document: turnstile(document).update(sitekey="0x4AAAAAAAAAAAAAAAAAAAAA"),
    )
    result = guard(SCRIPT, root, "--strict")
    assert (result.returncode, result.stderr) == (0, "")


def test_a_missing_data_file_fails(root: Path, guard: Guard) -> None:
    (root / EXAMPLES).unlink()
    fail_with(guard, root, EXAMPLES, "cannot read the file as JSON")


def test_pricing_without_a_field_fails(root: Path, guard: Guard) -> None:
    edit(root, PRICING, lambda document: document.pop("accessed"))
    fail_with(guard, root, PRICING, "invalid pricing data")


def test_pricing_with_cache_read_above_input_fails(root: Path, guard: Guard) -> None:
    def change(document: JsonObject) -> None:
        first = object_items(required_list(document, "models"), "models")[0]
        first["cache_read"] = 99.0

    edit(root, PRICING, change)
    fail_with(guard, root, PRICING, "cache_read of sonnet-5-5 is above its input price")


def test_an_example_order_missing_from_the_plan_fails(root: Path, guard: Guard) -> None:
    edit(root, EXAMPLES, lambda document: rows(document)[0].update(order="#1001"))
    fail_with(guard, root, EXAMPLES, "is not in the shipment plan")


def test_the_in_transit_example_must_be_in_transit_in_the_plan(root: Path, guard: Guard) -> None:
    edit(root, PLAN, set_plan_scenario("#1006", "DELIVERED"))
    fail_with(guard, root, EXAMPLES, "#1006 is DELIVERED in the plan")


def test_the_unfulfilled_example_must_be_unfulfilled_in_the_plan(root: Path, guard: Guard) -> None:
    edit(root, PLAN, set_plan_scenario("#1022", "IN_TRANSIT"))
    fail_with(guard, root, EXAMPLES, "#1022 is IN_TRANSIT in the plan")


def test_a_label_that_names_another_status_fails(root: Path, guard: Guard) -> None:
    edit(
        root, EXAMPLES, lambda document: rows(document)[1].update(label_key="try.example.delivered")
    )
    fail_with(guard, root, EXAMPLES, "the label key of #1022 does not name UNFULFILLED")


@pytest.mark.parametrize(
    "email", ["person@example.com", "ABCDEFGHIJ@orders.example.com", 7, "short@orders.example.com"]
)
def test_an_email_that_is_not_a_demo_address_fails(email: Json, root: Path, guard: Guard) -> None:
    edit(root, EXAMPLES, lambda document: rows(document)[0].update(email=email))
    fail_with(guard, root, EXAMPLES, "the email of #1006 is not a demo email address")


def test_an_example_row_with_a_missing_or_extra_key_fails(root: Path, guard: Guard) -> None:
    edit(root, EXAMPLES, lambda document: rows(document)[0].pop("scenario"))
    fail_with(guard, root, EXAMPLES, "row 'in-transit' must have exactly the keys")
    edit(root, EXAMPLES, lambda document: rows(document)[2].update(email=REAL_EMAIL))
    fail_with(guard, root, EXAMPLES, "row 'human' must have exactly the keys")


def test_the_example_list_must_keep_three_rows_with_one_human_row(root: Path, guard: Guard) -> None:
    edit(root, EXAMPLES, lambda document: document.update(examples=list[Json](rows(document)[:2])))
    fail_with(guard, root, EXAMPLES, "examples must be a list of 3 rows")


def test_runtime_with_an_extra_key_fails(root: Path, guard: Guard) -> None:
    edit(root, RUNTIME, lambda document: turnstile(document).update(secret="x"))
    fail_with(guard, root, RUNTIME, "turnstile must have exactly the keys")
    edit(root, RUNTIME, lambda document: document.update(gateway="https://example.com"))
    fail_with(guard, root, RUNTIME, "the only top-level key is")


def test_runtime_without_the_action_fails(root: Path, guard: Guard) -> None:
    edit(root, RUNTIME, lambda document: turnstile(document).pop("action"))
    fail_with(guard, root, RUNTIME, "turnstile must have exactly the keys")


def test_a_secret_like_string_in_place_of_the_sitekey_fails(root: Path, guard: Guard) -> None:
    edit(root, RUNTIME, lambda document: turnstile(document).update(sitekey=SECRET_LIKE))
    fail_with(guard, root, RUNTIME, "a secret key never belongs here")


def test_an_action_that_is_not_a_slug_fails(root: Path, guard: Guard) -> None:
    edit(root, RUNTIME, lambda document: turnstile(document).update(action="https://x.example/a"))
    fail_with(guard, root, RUNTIME, "action must be a lowercase slug")


@pytest.mark.parametrize("relative", [EXAMPLES, RUNTIME])
def test_a_file_that_is_not_an_object_fails(relative: str, root: Path, guard: Guard) -> None:
    (root / relative).write_text("[]\n", encoding="utf-8")
    fail_with(guard, root, relative, "the file must hold a JSON object")


def test_the_placeholder_patterns_come_from_the_release_lock_file(root: Path, guard: Guard) -> None:
    edit(root, EXAMPLES, lambda document: rows(document)[0].update(email=REAL_EMAIL))
    sync_public_emails(root)
    edit(root, RELEASE_LOCK, lambda document: document.update(placeholder_email="^abcdefghij@"))
    result = guard(SCRIPT, root)
    assert result.returncode == 0
    assert "the email of #1006 is still the placeholder" in result.stderr
    assert "the email of #1022 is still the placeholder" not in result.stderr


def test_a_missing_release_lock_file_fails(root: Path, guard: Guard) -> None:
    (root / RELEASE_LOCK).unlink()
    fail_with(guard, root, RELEASE_LOCK, "cannot read the file as JSON")


@pytest.mark.parametrize("key", ["placeholder_email", "test_sitekey"])
def test_a_release_lock_pattern_that_is_missing_or_invalid_fails(
    key: str, root: Path, guard: Guard
) -> None:
    edit(root, RELEASE_LOCK, lambda document: document.pop(key))
    fail_with(guard, root, RELEASE_LOCK, "placeholder patterns are missing or invalid")
    edit(root, RELEASE_LOCK, lambda document: document.update({key: "(["}))
    fail_with(guard, root, RELEASE_LOCK, "placeholder patterns are missing or invalid")


def test_the_email_shape_in_the_release_lock_accepts_every_address_the_generator_makes() -> None:
    lock = json.loads((REPO / RELEASE_LOCK).read_text(encoding="utf-8"))
    shape = re.compile(str(lock["email_shape"]))
    for number in range(1002, 1202):
        assert shape.fullmatch(demo_email("unit-test-secret", f"#{number}"))


def test_example_orders_must_be_public(root: Path, guard: Guard) -> None:
    edit(root, EXAMPLES, lambda document: rows(document)[0].update(order="#1098"))
    fail_with(guard, root, EXAMPLES, "example order #1098 is not in the public orders")
