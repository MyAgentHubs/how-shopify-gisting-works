import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from gisting.shopify.demo_config import load_config
from gisting.shopify.jsonvalue import (
    Json,
    MalformedResponse,
    connection_nodes,
    required_int,
    required_str,
)
from gisting.shopify.plan import dump_plan
from gisting.shopify.plan_build import OrderRef, PlanBuildError, build_plan

DEFAULT_ORDERS = Path("artifacts/shopify-seed-20260930/verified-orders.json")


def load_snapshot(path: Path) -> list[OrderRef]:
    document: Json = json.loads(path.read_text(encoding="utf-8"))
    nodes = document.get("orders") if isinstance(document, dict) else None
    if not isinstance(nodes, list):
        raise MalformedResponse("orders")
    refs: list[OrderRef] = []
    for node in nodes:
        if not isinstance(node, dict):
            raise MalformedResponse("orders")
        quantity = sum(
            required_int(line, "quantity") for line in connection_nodes(node, "lineItems")
        )
        refs.append(OrderRef(required_str(node, "name"), quantity))
    return refs


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate the demo shipment-state plan.")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--orders", type=Path, default=DEFAULT_ORDERS)
    parser.add_argument("--seed", type=int)
    args = parser.parse_args(argv)
    try:
        plan = build_plan(load_snapshot(args.orders), load_config(), args.seed)
    except (OSError, ValueError, PlanBuildError) as error:
        sys.stderr.write(f"demo_plan: {error}\n")
        return 1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(dump_plan(plan), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
