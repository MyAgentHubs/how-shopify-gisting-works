from dataclasses import dataclass

from gisting.shopify.jsonvalue import (
    Json,
    JsonObject,
    required_int,
    required_list,
    required_object,
    required_str,
    string_list,
)
from gisting.training.files import TEMPLATES_FILE, read_object

SPLITS = ("train", "dev")


@dataclass(frozen=True)
class Family:
    name: str
    split: str
    templates: tuple[str, ...]


@dataclass(frozen=True)
class Quota:
    train: int
    dev: int

    def of(self, split: str) -> int:
        return self.train if split == "train" else self.dev


def parse_families(node: JsonObject) -> tuple[Family, ...]:
    families: list[Family] = []
    for name in sorted(node):
        family = required_object(node, name)
        split = required_str(family, "split")
        if split not in SPLITS:
            message = f"family {name} has unknown split {split}"
            raise TypeError(message)
        families.append(Family(name, split, string_list(family, "templates")))
    return tuple(families)


def families_of(node: JsonObject, split: str) -> tuple[Family, ...]:
    return tuple(family for family in parse_families(node) if family.split == split)


def quota_of(node: JsonObject, prefix: str = "") -> Quota:
    return Quota(
        required_int(node, f"{prefix}train_count"), required_int(node, f"{prefix}dev_count")
    )


def load_document() -> JsonObject:
    return read_object(TEMPLATES_FILE)


def section(document: JsonObject, *path: str) -> JsonObject:
    node = document
    for key in path:
        node = required_object(node, key)
    return node


def forms(document: JsonObject) -> list[str]:
    return [item for item in required_list(document, "order_forms") if isinstance(item, str)]


def as_float(value: Json) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        message = "expected a number"
        raise TypeError(message)
    return float(value)
