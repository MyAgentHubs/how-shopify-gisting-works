from dataclasses import dataclass
from typing import Annotated

import pytest

from gisting.eval import dataclass_json
from gisting.eval.dataclass_json import DecodeError, decode_as, json_schema
from gisting.prompt import schema_marks
from gisting.prompt.schema_marks import MaxItems, MaxLength, Pattern

Name = Annotated[str, Pattern(r"^[a-z]+$"), MaxLength(4)]


@dataclass(frozen=True)
class Box:
    names: Annotated[tuple[Name, ...], MaxItems(2)]


def test_the_marks_live_below_both_eval_and_agent_and_stay_importable_from_the_generator() -> None:
    assert dataclass_json.Pattern is schema_marks.Pattern
    assert dataclass_json.MaxItems is schema_marks.MaxItems
    assert dataclass_json.MaxLength is schema_marks.MaxLength


def test_the_schema_carries_every_mark() -> None:
    names = json_schema(Box)["properties"]
    assert names == {
        "names": {
            "type": "array",
            "items": {"type": "string", "pattern": "^[a-z]+$", "maxLength": 4},
            "maxItems": 2,
        }
    }


@pytest.mark.parametrize("names", [[], ["abcd"], ["a", "bcde"]])
def test_a_document_within_the_marks_decodes(names: list[str]) -> None:
    assert decode_as(Box, {"names": names}) == Box(tuple(names))


@pytest.mark.parametrize(
    ("names", "where"),
    [
        (["a", "b", "c"], "names"),
        (["abcde"], "names[0]"),
        (["ABC"], "names[0]"),
        (["ok", "toolong"], "names[1]"),
    ],
)
def test_a_document_beyond_a_mark_is_rejected_at_the_right_place(
    names: list[str], where: str
) -> None:
    with pytest.raises(DecodeError, match=where.replace("[", r"\[").replace("]", r"\]")):
        decode_as(Box, {"names": names})
