import json
import os
from pathlib import Path

from gisting.shopify.demo_email import demo_email
from gisting.shopify.jsonvalue import (
    Json,
    JsonObject,
    MalformedResponse,
    object_items,
    required_list,
)
from gisting.shopify.order_name import InvalidOrderName, canonical_order_name

JSON_INDENT = 2
EXAMPLES_KEY = "examples"
ORDER_KEY = "order"
EMAIL_KEY = "email"


class ExampleOrdersError(ValueError):
    pass


def parse_rows(text: str, rows_key: str = EXAMPLES_KEY) -> tuple[JsonObject, list[JsonObject]]:
    try:
        document: Json = json.loads(text)
    except json.JSONDecodeError as error:
        message = "the orders file is not JSON"
        raise ExampleOrdersError(message) from error
    if not isinstance(document, dict):
        message = "the orders file is not an object"
        raise ExampleOrdersError(message)
    try:
        return document, object_items(required_list(document, rows_key), rows_key)
    except MalformedResponse as error:
        message = f"the orders file needs {rows_key} as a list of objects"
        raise ExampleOrdersError(message) from error


def canonical_known(raw: Json, known: frozenset[str]) -> str:
    try:
        order = canonical_order_name(raw) if isinstance(raw, str) else None
    except InvalidOrderName:
        order = None
    if order is None or order not in known:
        message = "an example order is not an order of the demo plan"
        raise ExampleOrdersError(message)
    return order


def fill_rows(rows: list[JsonObject], known: frozenset[str], secret: str) -> list[str]:
    orders = {
        index: canonical_known(row[ORDER_KEY], known)
        for index, row in enumerate(rows)
        if ORDER_KEY in row
    }
    if not orders:
        message = "the orders file has no example order to fill"
        raise ExampleOrdersError(message)
    for index, order in orders.items():
        rows[index][EMAIL_KEY] = demo_email(secret, order)
    return list(orders.values())


def write_atomically(path: Path, text: str) -> None:
    staging = path.with_name(f".{path.name}.tmp")
    staging.write_text(text, encoding="utf-8")
    os.replace(staging, path)


def fill_example_emails(
    path: Path, known: frozenset[str], secret: str, rows_key: str = EXAMPLES_KEY
) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        message = f"cannot read the orders file: {path}"
        raise ExampleOrdersError(message) from error
    document, rows = parse_rows(text, rows_key)
    filled = fill_rows(rows, known, secret)
    write_atomically(path, json.dumps(document, indent=JSON_INDENT) + "\n")
    return filled
