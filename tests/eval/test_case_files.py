import json
from pathlib import Path

from fakes.case_support import amend_many

from gisting.eval.case_files import load_cases

PLAN = Path(__file__).resolve().parents[2] / "data" / "demo-orders" / "shipment-plan-v1.json"


def line(**changes: object) -> str:
    return json.dumps(amend_many({key.replace("__", "."): v for key, v in changes.items()}))


def write(root: Path, relative: str, *lines: str, final_newline: bool = True) -> None:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines) + ("\n" if final_newline else ""), encoding="utf-8")
    plan = root / "data" / "demo-orders" / "shipment-plan-v1.json"
    plan.parent.mkdir(parents=True, exist_ok=True)
    plan.write_text(PLAN.read_text(encoding="utf-8"), encoding="utf-8")


def reasons(root: Path) -> list[str]:
    return [f"{p.path}:{p.line}: {p.reason}" for p in load_cases(root)[1]]


def test_no_cases_directory_is_not_a_problem(tmp_path: Path) -> None:
    assert load_cases(tmp_path) == ([], [])


def test_well_placed_cases_load(tmp_path: Path) -> None:
    write(tmp_path, "eval/cases/dev/other_order_probe.jsonl", line(), line(id="second_case"))
    cases, problems = load_cases(tmp_path)
    assert problems == []
    assert [item.case.id for item in cases] == ["unauthorized_other_order_001", "second_case"]
    assert [item.line for item in cases] == [1, 2]


def test_a_case_in_the_wrong_split_directory_is_reported(tmp_path: Path) -> None:
    write(tmp_path, "eval/cases/train/other_order_probe.jsonl", line())
    assert any("does not match directory train" in item for item in reasons(tmp_path))


def test_a_case_in_the_wrong_family_file_is_reported(tmp_path: Path) -> None:
    write(tmp_path, "eval/cases/dev/other.jsonl", line())
    assert any("does not match file name other.jsonl" in item for item in reasons(tmp_path))


def test_a_misplaced_file_is_reported(tmp_path: Path) -> None:
    write(tmp_path, "eval/cases/loose.jsonl", line())
    assert any("live in eval/cases/<split>/<family>.jsonl" in item for item in reasons(tmp_path))


def test_an_unknown_split_directory_is_reported(tmp_path: Path) -> None:
    write(tmp_path, "eval/cases/test/other_order_probe.jsonl", line())
    assert any("live in eval/cases" in item for item in reasons(tmp_path))


def test_malformed_lines_are_reported_with_their_number(tmp_path: Path) -> None:
    write(tmp_path, "eval/cases/dev/other_order_probe.jsonl", line(), "{oops", "", line(red_line=9))
    found = reasons(tmp_path)
    assert any(":2: invalid case:" in item for item in found)
    assert any(":3: blank line" in item for item in found)
    assert any(":4: invalid case: red_line" in item for item in found)


def test_a_missing_final_newline_is_reported(tmp_path: Path) -> None:
    write(tmp_path, "eval/cases/dev/other_order_probe.jsonl", line(), final_newline=False)
    assert any("no final newline" in item for item in reasons(tmp_path))


def test_duplicate_ids_across_files_are_reported(tmp_path: Path) -> None:
    write(tmp_path, "eval/cases/dev/other_order_probe.jsonl", line())
    write(tmp_path, "eval/cases/train/second.jsonl", line(split="train", family="second"))
    found = reasons(tmp_path)
    assert len(found) == 1
    assert "already used at eval/cases/dev/other_order_probe.jsonl:1" in found[0]


def test_an_unknown_plan_or_order_is_reported(tmp_path: Path) -> None:
    write(tmp_path, "eval/cases/dev/other_order_probe.jsonl", line(fixtures__plan="nope.json"))
    assert any("plan nope.json is missing" in item for item in reasons(tmp_path))
    write(
        tmp_path,
        "eval/cases/dev/other_order_probe.jsonl",
        line(fixtures__canary={"allowed": ["#1002"], "forbidden": ["#9999"]}),
    )
    assert any("order #9999 is not in the plan" in item for item in reasons(tmp_path))
