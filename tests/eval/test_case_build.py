import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

from gisting.eval.case_build import TemplateError, build_cases
from gisting.eval.case_files import CASES_DIR, load_cases

ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = ROOT / "data" / "eval" / "redline3-templates.json"
PLAN = ROOT / "data" / "demo-orders" / "shipment-plan-v1.json"
MINIMUM_CASES = 100


def sandbox(tmp_path: Path, families: dict[str, object]) -> Path:
    document = json.loads(TEMPLATES.read_text(encoding="utf-8"))
    document["families"] = families
    (tmp_path / "data" / "eval").mkdir(parents=True)
    (tmp_path / "data" / "demo-orders").mkdir(parents=True)
    (tmp_path / "data" / "eval" / TEMPLATES.name).write_text(json.dumps(document), encoding="utf-8")
    (tmp_path / "data" / "demo-orders" / PLAN.name).write_text(
        PLAN.read_text(encoding="utf-8"), encoding="utf-8"
    )
    return tmp_path


def family(content: str, **changes: object) -> dict[str, object]:
    base: dict[str, object] = {
        "split": "dev",
        "category": "probe",
        "orders": [{"letter": "a", "email": "absent"}],
        "allowed": [],
        "forbidden": ["a"],
        "expect_order": None,
        "templates": [[{"role": "user", "content": content}]],
    }
    return base | changes


RED_LINES = (1, 3, 4)


def run_cli(*arguments: str, red_line: int = 3) -> bytes:
    command = [sys.executable, "-m", "gisting.eval", "build-cases", "--red-line", str(red_line)]
    return subprocess.run([*command, *arguments], capture_output=True, check=True, cwd=ROOT).stdout


@pytest.mark.parametrize("red_line", RED_LINES)
def test_building_twice_gives_identical_cases(red_line: int) -> None:
    assert build_cases(ROOT, red_line) == build_cases(ROOT, red_line)


@pytest.mark.parametrize("red_line", RED_LINES)
def test_the_cli_prints_the_same_bytes_every_time(red_line: int) -> None:
    assert run_cli(red_line=red_line) == run_cli(red_line=red_line)


def test_committed_case_files_equal_the_generated_output(tmp_path: Path) -> None:
    for red_line in RED_LINES:
        run_cli("--out", str(tmp_path), red_line=red_line)
    for generated in sorted(tmp_path.rglob("*.jsonl")):
        committed = ROOT / CASES_DIR / generated.relative_to(tmp_path)
        assert committed.read_bytes() == generated.read_bytes()
    assert len(list(tmp_path.rglob("*.jsonl"))) == len(list((ROOT / CASES_DIR).rglob("*.jsonl")))


def test_the_committed_cases_are_valid_and_cover_train_and_dev() -> None:
    cases, problems = load_cases(ROOT)
    assert problems == []
    assert len(cases) >= MINIMUM_CASES
    assert {item.case.split for item in cases} == {"train", "dev"}
    assert {item.case.red_line for item in cases} == {1, 3, 4, "none"}


def test_every_case_forbids_an_order_the_customer_is_not_allowed_to_see() -> None:
    for case in build_cases(ROOT, 3):
        canary = case.fixtures.canary
        assert canary.forbidden
        assert not set(canary.allowed) & set(canary.forbidden)


def test_every_family_has_a_single_split() -> None:
    splits = Counter((case.family, case.split) for case in build_cases(ROOT, 3))
    assert len({family for family, _ in splits}) == len(splits)


@pytest.mark.parametrize(
    "content",
    ["Is {order_b} shipped?", "My email is {email_a}.", "Look at {ordr_a}"],
)
def test_a_slot_without_a_matching_order_is_refused(tmp_path: Path, content: str) -> None:
    with pytest.raises(TemplateError):
        build_cases(sandbox(tmp_path, {"probe_family": family(content)}), 3)


def test_a_wrong_split_name_is_refused(tmp_path: Path) -> None:
    with pytest.raises(TemplateError):
        build_cases(sandbox(tmp_path, {"probe_family": family("Hi {order_a}", split="test")}), 3)


def test_a_sealed_family_is_refused_instead_of_written_in_plaintext(tmp_path: Path) -> None:
    with pytest.raises(TemplateError, match="E6"):
        build_cases(sandbox(tmp_path, {"probe_family": family("Hi {order_a}", split="sealed")}), 3)


def test_the_cli_exits_non_zero_for_a_sealed_family(tmp_path: Path) -> None:
    root = sandbox(tmp_path, {"probe_family": family("Hi {order_a}", split="sealed")})
    command = [sys.executable, "-m", "gisting.eval", "build-cases", "--red-line", "3"]
    result = subprocess.run(
        [*command, "--root", str(root)], capture_output=True, text=True, check=False, cwd=ROOT
    )
    assert (result.returncode, result.stdout) == (1, "")
    assert "E6" in result.stderr


def test_the_committed_sealed_directory_holds_no_plaintext() -> None:
    names = {path.name for path in (ROOT / CASES_DIR / "sealed").iterdir()}
    assert names <= {".gitkeep"}


def test_a_family_may_override_the_red_line_and_set_the_expected_action(tmp_path: Path) -> None:
    changes = {"red_line": "none", "scenario": "ask"}
    root = sandbox(tmp_path, {"probe_family": family("Hi {order_a}", **changes)})
    (case,) = build_cases(root, 3)
    assert (case.red_line, case.expect.scenario) == ("none", "ask")


def test_a_family_without_overrides_keeps_the_document_red_line(tmp_path: Path) -> None:
    (case,) = build_cases(sandbox(tmp_path, {"probe_family": family("Hi {order_a}")}), 3)
    assert (case.red_line, case.expect.scenario) == (3, None)


def add_template_file(root: Path, suffix: str, families: dict[str, object]) -> None:
    document = json.loads(TEMPLATES.read_text(encoding="utf-8"))
    document["families"] = families
    name = TEMPLATES.name.replace("-templates", f"-templates-{suffix}")
    (root / "data" / "eval" / name).write_text(json.dumps(document), encoding="utf-8")


def test_a_second_template_file_adds_its_families_after_the_base_file(tmp_path: Path) -> None:
    root = sandbox(tmp_path, {"first_family": family("Hi {order_a}")})
    add_template_file(root, "one", {"second_family": family("Yo {order_a}")})
    add_template_file(root, "two", {"third_family": family("Hey {order_a}")})
    assert [case.family for case in build_cases(root, 3)] == [
        "first_family",
        "second_family",
        "third_family",
    ]


def test_a_family_name_used_in_two_template_files_is_refused(tmp_path: Path) -> None:
    root = sandbox(tmp_path, {"same_family": family("Hi {order_a}")})
    add_template_file(root, "more", {"same_family": family("Yo {order_a}")})
    with pytest.raises(TemplateError, match="same_family"):
        build_cases(root, 3)


def test_a_template_file_of_another_red_line_is_not_read(tmp_path: Path) -> None:
    root = sandbox(tmp_path, {"first_family": family("Hi {order_a}")})
    other = root / "data" / "eval" / "redline4-templates-more.json"
    other.write_text("not json", encoding="utf-8")
    assert [case.family for case in build_cases(root, 3)] == ["first_family"]


def test_a_template_file_whose_red_line_differs_from_its_name_is_refused(tmp_path: Path) -> None:
    root = sandbox(tmp_path, {"first_family": family("Hi {order_a}")})
    add_template_file(root, "more", {"second_family": family("Yo {order_a}")})
    path = root / "data" / "eval" / TEMPLATES.name.replace("-templates", "-templates-more")
    document = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps({**document, "red_line": 4}), encoding="utf-8")
    with pytest.raises(TemplateError, match="red_line"):
        build_cases(root, 3)
