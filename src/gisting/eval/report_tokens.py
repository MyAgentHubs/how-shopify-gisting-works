from collections.abc import Sequence

from gisting.shopify.jsonvalue import Json, JsonObject

DIGITS = 3


def mean(values: Sequence[int | float]) -> float | None:
    return round(sum(values) / len(values), DIGITS) if values else None


def as_object(value: Json) -> JsonObject:
    return value if isinstance(value, dict) else {}


def number(node: JsonObject, key: str) -> int:
    value = node.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def model_calls(row: JsonObject) -> list[JsonObject]:
    calls = as_object(row.get("internal")).get("model_calls")
    return [call for call in calls if isinstance(call, dict)] if isinstance(calls, list) else []


def token_metrics(rows: Sequence[JsonObject], mode: str) -> JsonObject:
    prefill: list[int] = []
    total: list[int] = []
    rules_per_call: list[int] = []
    for row in rows:
        calls = model_calls(row)
        if not calls:
            continue
        prefill.append(sum(number(as_object(call.get("tokens")), "total") for call in calls))
        total.append(prefill[-1] + sum(number(call, "output_tokens") for call in calls))
        rules_per_call += [number(as_object(call.get("tokens")), "rules") for call in calls]
    rules_mean = mean(rules_per_call)
    return {
        "turns": len(prefill),
        "model_calls": len(rules_per_call),
        "prefill_tokens_per_turn": mean(prefill),
        "total_tokens_per_turn": mean(total),
        "rules_tokens_per_call": rules_mean,
        "gist_token_count": rules_mean if mode == "gist" else None,
    }
