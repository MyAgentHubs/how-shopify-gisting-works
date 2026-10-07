from dataclasses import dataclass
from typing import Annotated, Literal

import pytest

from gisting.eval.dataclass_json import DecodeError, Pattern, decode_as, json_schema

Kind = Literal[1, "none"]
Slug = Annotated[str, Pattern(r"^[a-z]+$")]


@dataclass(frozen=True)
class Inner:
    label: Slug
    weight: float


@dataclass(frozen=True)
class Outer:
    kind: Kind
    inner: Inner
    tags: tuple[str, ...]
    extra: dict[str, str]
    note: str | None
    flag: bool
    count: int


GOOD = {
    "kind": "none",
    "inner": {"label": "abc", "weight": 2},
    "tags": ["a"],
    "extra": {"k": "v"},
    "note": None,
    "flag": True,
    "count": 3,
}


def with_change(**changes: object) -> dict[str, object]:
    return {**GOOD, **changes}


@pytest.mark.parametrize(
    "weight", [float("nan"), float("inf"), float("-inf"), pytest.param(10**400, id="huge-int")]
)
def test_a_number_that_is_not_finite_is_rejected(weight: float) -> None:
    inner = {"label": "abc", "weight": weight}
    with pytest.raises(DecodeError, match=r"inner\.weight: expected a finite number"):
        decode_as(Outer, with_change(inner=inner))


def test_a_valid_document_decodes_to_the_dataclass() -> None:
    outer = decode_as(Outer, GOOD)
    assert outer == Outer("none", Inner("abc", 2.0), ("a",), {"k": "v"}, None, True, 3)


@pytest.mark.parametrize(
    ("changes", "where"),
    [
        ({"kind": True}, "kind"),
        ({"kind": 2}, "kind"),
        ({"inner": {"label": "ABC", "weight": 1}}, "inner.label"),
        ({"inner": {"label": "abc"}}, "inner"),
        ({"inner": {"label": "abc", "weight": True}}, "inner.weight"),
        ({"tags": "a"}, "tags"),
        ({"tags": [1]}, "tags[0]"),
        ({"extra": {"k": 1}}, "extra.k"),
        ({"note": 5}, "note"),
        ({"flag": 1}, "flag"),
        ({"count": 1.5}, "count"),
        ({"count": True}, "count"),
    ],
)
def test_a_wrong_value_is_rejected_with_its_path(changes: dict[str, object], where: str) -> None:
    with pytest.raises(DecodeError, match=where.replace("[", r"\[").replace("]", r"\]")):
        decode_as(Outer, with_change(**changes))


def test_unknown_and_missing_keys_are_rejected() -> None:
    with pytest.raises(DecodeError, match="unknown"):
        decode_as(Outer, {**GOOD, "surprise": 1})
    with pytest.raises(DecodeError, match="missing"):
        decode_as(Outer, {key: value for key, value in GOOD.items() if key != "count"})


def test_a_non_object_document_is_rejected() -> None:
    with pytest.raises(DecodeError):
        decode_as(Outer, [GOOD])


def test_the_schema_describes_every_field_and_forbids_extras() -> None:
    schema = json_schema(Outer)
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert schema["required"] == list(GOOD)
    properties = schema["properties"]
    assert isinstance(properties, dict)
    assert properties["kind"] == {"enum": [1, "none"]}
    assert properties["note"] == {"anyOf": [{"type": "string"}, {"type": "null"}]}
    assert properties["tags"] == {"type": "array", "items": {"type": "string"}}
    assert properties["inner"]["properties"]["label"] == {"type": "string", "pattern": "^[a-z]+$"}
    assert properties["inner"]["properties"]["weight"] == {"type": "number"}


@dataclass(frozen=True)
class WithDefault:
    name: str
    note: str | None = None


def test_a_field_with_a_default_may_be_left_out_and_is_not_required_in_the_schema() -> None:
    assert decode_as(WithDefault, {"name": "a"}) == WithDefault("a", None)
    assert decode_as(WithDefault, {"name": "a", "note": "b"}) == WithDefault("a", "b")
    assert json_schema(WithDefault)["required"] == ["name"]
    with pytest.raises(DecodeError, match="missing"):
        decode_as(WithDefault, {"note": "b"})
