import json
import shutil
from pathlib import Path

from conftest import SCRIPTS_DIR, Guard

REPO = SCRIPTS_DIR.parent
SCRIPT = "check_benchmarks_data.py"
SOURCE = "apps/web/data/benchmarks_source.json"
OUTPUT = "apps/web/data/benchmarks.json"
TREE = json.loads((REPO / SOURCE).read_text(encoding="utf-8"))["code_tree_sha"]


def copy_inputs(root: Path) -> Path:
    shutil.copytree(REPO / "eval" / "reports" / TREE, root / "eval" / "reports" / TREE)
    (root / "apps" / "web" / "data").mkdir(parents=True)
    shutil.copyfile(REPO / SOURCE, root / SOURCE)
    return root


def test_the_committed_benchmarks_data_is_up_to_date(guard: Guard) -> None:
    result = guard(SCRIPT, REPO)
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")


def test_a_missing_data_file_fails(tmp_path: Path, guard: Guard) -> None:
    result = guard(SCRIPT, copy_inputs(tmp_path))
    assert result.returncode == 1
    assert f"{OUTPUT}:1: file is missing" in result.stderr


def test_write_creates_data_that_passes_the_guard(tmp_path: Path, guard: Guard) -> None:
    root = copy_inputs(tmp_path)
    assert guard(SCRIPT, root, "--write").returncode == 0
    assert guard(SCRIPT, root).returncode == 0


def test_a_data_file_that_differs_from_the_reports_fails(tmp_path: Path, guard: Guard) -> None:
    root = copy_inputs(tmp_path)
    guard(SCRIPT, root, "--write")
    target = root / OUTPUT
    document = json.loads(target.read_text(encoding="utf-8"))
    document["tokens"]["gist"]["rules_tokens_per_call"] = 1.0
    target.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    result = guard(SCRIPT, root)
    assert result.returncode == 1
    assert f"{OUTPUT}:1: differs from the committed eval reports" in result.stderr


def test_a_missing_report_fails(tmp_path: Path, guard: Guard) -> None:
    (tmp_path / "apps" / "web" / "data").mkdir(parents=True)
    shutil.copyfile(REPO / SOURCE, tmp_path / SOURCE)
    result = guard(SCRIPT, tmp_path)
    assert result.returncode == 1
    assert f"{SOURCE}:1: cannot build the benchmarks data" in result.stderr
