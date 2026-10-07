from typing import TypeAlias

Json: TypeAlias = dict[str, "Json"] | list["Json"] | str | int | float | bool | None
JsonObject: TypeAlias = dict[str, Json]
GID_PREFIX = "gid://shopify/"
PAIR_LENGTH = 2


class MalformedResponse(ValueError):
    pass


def as_object(value: Json) -> JsonObject | None:
    return value if isinstance(value, dict) else None


def required_object(parent: JsonObject, key: str) -> JsonObject:
    value = parent.get(key)
    if not isinstance(value, dict):
        raise MalformedResponse(key)
    return value


def required_list(parent: JsonObject, key: str) -> list[Json]:
    value = parent.get(key)
    if not isinstance(value, list):
        raise MalformedResponse(key)
    return value


def required_str(parent: JsonObject, key: str) -> str:
    value = parent.get(key)
    if not isinstance(value, str):
        raise MalformedResponse(key)
    return value


def optional_str(parent: JsonObject, key: str) -> str | None:
    value = parent.get(key)
    if value is not None and not isinstance(value, str):
        raise MalformedResponse(key)
    return value


def required_int(parent: JsonObject, key: str) -> int:
    value = parent.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise MalformedResponse(key)
    return value


def required_bool(parent: JsonObject, key: str) -> bool:
    value = parent.get(key)
    if not isinstance(value, bool):
        raise MalformedResponse(key)
    return value


def object_items(items: list[Json], key: str) -> list[JsonObject]:
    found: list[JsonObject] = []
    for item in items:
        if not isinstance(item, dict):
            raise MalformedResponse(key)
        found.append(item)
    return found


def connection_nodes(parent: JsonObject, key: str) -> list[JsonObject]:
    return object_items(required_list(required_object(parent, key), "nodes"), key)


def string_list(parent: JsonObject, key: str) -> tuple[str, ...]:
    values = required_list(parent, key)
    if not all(isinstance(value, str) for value in values):
        raise MalformedResponse(key)
    return tuple(value for value in values if isinstance(value, str))


def collect_gids(value: Json) -> set[str]:
    if isinstance(value, str):
        return {value} if value.startswith(GID_PREFIX) else set()
    children: list[Json] = []
    if isinstance(value, dict):
        children = list(value.values())
    elif isinstance(value, list):
        children = value
    found: set[str] = set()
    for child in children:
        found |= collect_gids(child)
    return found


def optional_object(parent: JsonObject, key: str) -> JsonObject | None:
    value = parent.get(key)
    if value is not None and not isinstance(value, dict):
        raise MalformedResponse(key)
    return value


def as_pair(value: Json, key: str) -> tuple[int, int]:
    if not isinstance(value, list):
        raise MalformedResponse(key)
    numbers = [item for item in value if isinstance(item, int)]
    if len(value) != PAIR_LENGTH or len(numbers) != PAIR_LENGTH:
        raise MalformedResponse(key)
    return numbers[0], numbers[1]


def required_pair(parent: JsonObject, key: str) -> tuple[int, int]:
    return as_pair(parent.get(key), key)
