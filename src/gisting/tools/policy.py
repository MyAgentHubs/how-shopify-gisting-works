import json
from dataclasses import dataclass
from pathlib import Path

from gisting.shopify.jsonvalue import (
    Json,
    JsonObject,
    MalformedResponse,
    required_int,
    required_object,
    required_str,
    string_list,
)
from gisting.tools.facts import FIELD_NAMES, Source

POLICY_FILE = Path(__file__).resolve().parents[3] / "prompts" / "lookup_order.policy.json"


class PolicyError(ValueError):
    pass


@dataclass(frozen=True)
class LookupPolicy:
    order_min: int
    order_max: int
    failure_limit: int
    cache_ttl_seconds: int
    required_tags: tuple[str, ...]
    sources: dict[str, Source]


def parse_sources(node: JsonObject) -> dict[str, Source]:
    sources = {name: Source(required_str(node, name)) for name in FIELD_NAMES}
    if set(node) != set(FIELD_NAMES):
        raise MalformedResponse("field_sources")
    return sources


def parse_policy(document: Json) -> LookupPolicy:
    if not isinstance(document, dict):
        raise MalformedResponse("policy")
    limits = required_object(document, "order_range")
    policy = LookupPolicy(
        order_min=required_int(limits, "min"),
        order_max=required_int(limits, "max"),
        failure_limit=required_int(document, "failure_limit_per_session"),
        cache_ttl_seconds=required_int(document, "cache_ttl_seconds"),
        required_tags=string_list(document, "required_tags"),
        sources=parse_sources(required_object(document, "field_sources")),
    )
    if policy.order_min > policy.order_max or policy.failure_limit < 1 or not policy.required_tags:
        message = "policy limits"
        raise MalformedResponse(message)
    return policy


def load_policy(path: Path = POLICY_FILE) -> LookupPolicy:
    try:
        return parse_policy(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError) as error:
        message = f"{type(error).__name__}: {error}"
        raise PolicyError(message) from error
