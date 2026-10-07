import json
from pathlib import Path

import pytest
from fakes.agent_launch import inprocess_launcher

from gisting.eval.case_files import load_cases
from gisting.eval.cli import main
from gisting.eval.runner import RunSpec, Selection, run_cases, select_cases

ROOT = Path(__file__).resolve().parents[2]
SECRET = "grade-cli-secret-value"
LOADED, _PROBLEMS = load_cases(ROOT)


def run_small(directory: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("GISTING_EMAIL_SECRET", SECRET)
    env_file = directory / "empty.env"
    env_file.write_text("")
    cases = select_cases(LOADED, Selection(("dev",), per_red_line=2))
    spec = RunSpec(ROOT, "full", directory, inprocess_launcher(env_file), env_file=env_file)
    return run_cases(spec, cases).path


def test_grade_writes_the_report_next_to_the_transcripts_and_prints_the_counts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run_small(tmp_path, monkeypatch)
    assert main(["grade", "--dir", str(tmp_path), "--code-tree-sha", "abc"]) == 0
    out = capsys.readouterr().out
    assert "fact_provenance_failures final: 0 / 2 (95% upper bound " in out
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert report["run"]["code_tree_sha"] == "abc"
    assert (tmp_path / "report.json").read_text(encoding="utf-8").endswith("}\n")
    assert SECRET not in (tmp_path / "report.json").read_text(encoding="utf-8")


def test_grading_twice_gives_byte_identical_reports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_small(tmp_path, monkeypatch)
    argv = ["grade", "--dir", str(tmp_path), "--code-tree-sha", "abc"]
    assert main(argv) == 0
    first = (tmp_path / "report.json").read_bytes()
    assert main(argv) == 0
    assert (tmp_path / "report.json").read_bytes() == first


def test_a_run_error_makes_the_grade_exit_non_zero_but_still_writes_the_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = run_small(tmp_path, monkeypatch)
    lines = path.read_text(encoding="utf-8").splitlines()
    first = json.loads(lines[0])
    lines[0] = json.dumps({"case_id": first["case_id"], "mode": "full", "error": {"type": "x"}})
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert main(["grade", "--dir", str(tmp_path), "--code-tree-sha", "abc"]) == 1
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert report["cases"]["run_errors"] == [first["case_id"]]


def test_missing_transcripts_are_a_usage_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["grade", "--dir", str(tmp_path), "--code-tree-sha", "abc"]) == 2
    assert "not found" in capsys.readouterr().err
    assert not (tmp_path / "report.json").exists()
