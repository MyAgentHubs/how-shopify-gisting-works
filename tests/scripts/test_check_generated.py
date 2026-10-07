import json
from pathlib import Path

from conftest import SCRIPTS_DIR, Guard, Populate

from gisting.eval.case_spec import EvalCase
from gisting.eval.dataclass_json import json_schema

REPO = SCRIPTS_DIR.parent
CONTRACT = "contracts/eval_case.schema.json"
TS_CONTRACT = "contracts/eval_case.generated.ts"


def expected_text() -> str:
    return json.dumps(json_schema(EvalCase), indent=2) + "\n"


def test_the_committed_contracts_are_up_to_date(guard: Guard) -> None:
    result = guard("check_generated.py", REPO)
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")


def test_a_missing_contract_fails(populate: Populate, guard: Guard) -> None:
    result = guard("check_generated.py", populate({"README": "x"}))
    assert result.returncode == 1
    assert f"{CONTRACT}:1: file is missing" in result.stderr


def test_a_stale_contract_fails(populate: Populate, guard: Guard) -> None:
    result = guard("check_generated.py", populate({CONTRACT: expected_text() + " "}))
    assert result.returncode == 1
    assert f"{CONTRACT}:1: differs from the generated output" in result.stderr


def test_write_regenerates_a_stale_contract(populate: Populate, guard: Guard) -> None:
    root = populate({CONTRACT: "{}"})
    assert guard("check_generated.py", root, "--write").returncode == 0
    assert (root / CONTRACT).read_text(encoding="utf-8") == expected_text()
    assert guard("check_generated.py", root).returncode == 0


def test_write_creates_the_contracts_directory(tmp_path: Path, guard: Guard) -> None:
    assert guard("check_generated.py", tmp_path, "--write").returncode == 0
    assert (tmp_path / CONTRACT).is_file()


def test_a_stale_typescript_contract_fails(populate: Populate, guard: Guard) -> None:
    root = populate({CONTRACT: expected_text(), TS_CONTRACT: "export type EvalCase = {};\n"})
    result = guard("check_generated.py", root)
    assert result.returncode == 1
    assert f"{TS_CONTRACT}:1: differs from the generated output" in result.stderr
    assert f"{CONTRACT}:1" not in result.stderr


def test_a_stale_public_trace_contract_fails(populate: Populate, guard: Guard) -> None:
    path = "contracts/public_trace.schema.json"
    result = guard("check_generated.py", populate({path: "{}"}))
    assert result.returncode == 1
    assert f"{path}:1: differs from the generated output" in result.stderr
