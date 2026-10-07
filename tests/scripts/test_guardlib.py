import subprocess
from pathlib import Path

from conftest import Guard, Populate


def test_git_repositories_skip_ignored_files(populate: Populate, guard: Guard) -> None:
    root = populate({
        ".gitignore": "scratch.py\n",
        "scratch.py": "# private\n",
        "src/a.py": "x = 1\n",
    })
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    assert guard("check_no_comments.py", root).returncode == 0
    (root / "src/b.py").write_text("# tracked-or-not, still checked\n")
    assert guard("check_no_comments.py", root).returncode == 1


def test_plain_directories_are_walked(populate: Populate, guard: Guard) -> None:
    root: Path = populate({"src/a.py": "# no git here\n"})
    assert guard("check_no_comments.py", root).returncode == 1
