import json
from pathlib import Path

import pytest
from fakes.case_support import GOOD, amend

from gisting.eval.case_spec import EvalCase
from gisting.eval.dataclass_json import DecodeError, decode_as, json_schema

CONTRACT = Path(__file__).resolve().parents[2] / "contracts" / "eval_case.schema.json"


def test_a_well_formed_case_decodes() -> None:
    case = decode_as(EvalCase, GOOD)
    assert (case.id, case.red_line, case.split) == ("unauthorized_other_order_001", 3, "dev")
    assert case.fixtures.orders[0].email == "matching"


@pytest.mark.parametrize(
    "document",
    [
        amend("red_line", 5),
        amend("red_line", "3"),
        amend("split", "test"),
        amend("id", "Has Space"),
        amend("family", ""),
        amend("messages", [{"role": "system"}]),
        amend("fixtures.orders", [{"order": "1002", "email": "matching"}]),
        amend("fixtures.plan", "../escape.json"),
        amend("expect.turn", "third"),
    ],
)
def test_a_malformed_case_is_rejected(document: dict[str, object]) -> None:
    with pytest.raises(DecodeError):
        decode_as(EvalCase, document)


def test_the_control_group_is_a_valid_red_line() -> None:
    assert decode_as(EvalCase, amend("red_line", "none")).red_line == "none"


def test_the_committed_contract_is_generated_from_the_model() -> None:
    committed = json.loads(CONTRACT.read_text(encoding="utf-8"))
    assert committed == json_schema(EvalCase)
