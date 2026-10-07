import json
import shutil
from pathlib import Path

import pytest
from conftest import SCRIPTS_DIR, Guard

from gisting.shopify.jsonvalue import Json, JsonObject, object_items, required_list

REPO = SCRIPTS_DIR.parent
PUBLIC = "apps/web/data/public_orders.json"
PIN = "apps/web/data/public_orders_pin.json"
FILES = (
    PUBLIC,
    PIN,
    "apps/web/data/example_orders.json",
    "apps/web/data/pricing.json",
    "apps/web/data/runtime.json",
    "apps/web/data/release_lock.json",
    "data/demo-orders/shipment-plan-v1.json",
)


@pytest.fixture
def root(tmp_path: Path) -> Path:
    for relative in FILES:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO / relative, target)
    return tmp_path


def public_rows(root: Path) -> list[JsonObject]:
    document: Json = json.loads((root / PUBLIC).read_text())
    assert isinstance(document, dict)
    return object_items(required_list(document, "orders"), "orders")


def write_rows(root: Path, rows: list[JsonObject]) -> None:
    (root / PUBLIC).write_text(json.dumps({"orders": rows}) + "\n")


def assert_failure(root: Path, guard: Guard, fragment: str) -> None:
    result = guard("check_page_data.py", root)
    assert result.returncode == 1, result.stderr
    assert any(
        line.startswith(f"{PUBLIC}:1:") and fragment in line for line in result.stderr.splitlines()
    ), result.stderr


@pytest.mark.parametrize("count", [7, 9])
def test_public_orders_require_exactly_eight_rows(count: int, root: Path, guard: Guard) -> None:
    rows = public_rows(root)
    write_rows(root, (rows + [rows[0]])[:count])
    assert_failure(root, guard, "orders must be a list of 8 rows")


@pytest.mark.parametrize(
    ("field", "value", "fragment"),
    [
        ("scenario", "DELIVERED", "#1006 is IN_TRANSIT in the plan"),
        ("order", "#1097", "public order values must be unique"),
        ("id", "unfulfilled", "public id values must be unique"),
        ("email", "person@example.com", "not a demo email address"),
        ("email", "abcdefghij@orders.example.com", "must match example_orders.json"),
        ("order", "#9999", "not in the shipment plan"),
        ("order", "1006", "canonical order numbers"),
        ("label_key", "try.example.delivered", "does not name IN_TRANSIT"),
    ],
)
def test_invalid_public_order_fails(
    field: str, value: str, fragment: str, root: Path, guard: Guard
) -> None:
    rows = public_rows(root)
    rows[0][field] = value
    write_rows(root, rows)
    assert_failure(root, guard, fragment)


@pytest.mark.parametrize("extra", [False, True])
def test_public_order_keys_are_exact(extra: bool, root: Path, guard: Guard) -> None:
    rows = public_rows(root)
    if extra:
        rows[0]["unexpected"] = "value"
    else:
        rows[0].pop("scenario")
    write_rows(root, rows)
    assert_failure(root, guard, "must have exactly the keys")


def test_public_placeholder_is_a_pending_note(root: Path, guard: Guard) -> None:
    rows = public_rows(root)
    rows[1]["email"] = "xxxxxxxxxx@orders.example.com"
    write_rows(root, rows)
    result = guard("check_page_data.py", root)
    assert result.returncode == 0
    assert f"note: {PUBLIC}: the email of #1097 is still the placeholder" in result.stderr
    assert guard("check_page_data.py", root, "--strict").returncode == 1


@pytest.mark.parametrize("rows", [None, {}, [1] * 8])
def test_malformed_public_rows_fail(rows: Json, root: Path, guard: Guard) -> None:
    (root / PUBLIC).write_text(json.dumps({"orders": rows}))
    assert_failure(root, guard, "must be an object" if isinstance(rows, list) else "list of 8")


def test_public_order_set_is_pinned(root: Path, guard: Guard) -> None:
    rows = public_rows(root)
    rows[0]["order"] = "#1098"
    write_rows(root, rows)
    assert_failure(root, guard, "public orders must be exactly the pinned set")
    result = guard("check_page_data.py", root)
    assert "unexpected: ['#1098'], missing: ['#1006']" in result.stderr


def test_public_emails_must_be_unique(root: Path, guard: Guard) -> None:
    rows = public_rows(root)
    rows[2]["email"] = rows[1]["email"]
    write_rows(root, rows)
    assert_failure(root, guard, "public emails must be unique")


def test_missing_public_order_pin_fails(root: Path, guard: Guard) -> None:
    (root / PIN).unlink()
    result = guard("check_page_data.py", root)
    assert result.returncode == 1
    assert f"{PIN}:1: cannot read the file as JSON" in result.stderr


@pytest.mark.parametrize(
    "orders",
    [
        ["#1006", "#1097", "#1016", "#1021", "#1084", "#1012", "#1005"],
        ["#1006"] * 8,
        ["1006", "#1097", "#1016", "#1021", "#1084", "#1012", "#1005", "#1022"],
        [1006, "#1097", "#1016", "#1021", "#1084", "#1012", "#1005", "#1022"],
        None,
    ],
)
def test_invalid_public_order_pin_fails(orders: Json, root: Path, guard: Guard) -> None:
    (root / PIN).write_text(json.dumps({"orders": orders}))
    result = guard("check_page_data.py", root)
    assert result.returncode == 1
    assert f"{PIN}:1: pin must hold exactly 8 distinct canonical order names" in result.stderr


@pytest.mark.parametrize("document", ["not JSON", "[]", "{}"])
def test_malformed_public_order_pin_fails(document: str, root: Path, guard: Guard) -> None:
    (root / PIN).write_text(document)
    result = guard("check_page_data.py", root)
    assert result.returncode == 1
    assert f"{PIN}:1:" in result.stderr
