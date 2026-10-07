from pathlib import Path

from conftest import Guard, Populate

PYTHON_USES = (
    "import os\n"
    "a = os.environ['ALPHA']\n"
    "b = os.environ.get('BETA', '')\n"
    "c = os.getenv('GAMMA')\n"
    "d = os.environ.get('HOME')\n"
)
SHELL_USES = (
    '#!/usr/bin/env bash\necho "${DELTA:-x}" "$EPSILON" "$HOME" "$lower" "${BASH_SOURCE[0]}"\n'
)
TS_USES = "const a = process.env.ZETA;\nconst b = env.ETA;\nconst c = process.env['THETA'];\n"
ALL_KEYS = "ALPHA=\nBETA=x\nGAMMA=\nDELTA=\nEPSILON=\nZETA=\nETA=\nTHETA=\n"


def repo(populate: Populate, example: str | None) -> Path:
    files = {
        "src/gisting/a.py": PYTHON_USES,
        "scripts/a.sh": SHELL_USES,
        "apps/gateway/a.ts": TS_USES,
    }
    if example is not None:
        files[".env.example"] = example
    return populate(files)


def test_matching_example_passes(populate: Populate, guard: Guard) -> None:
    root = repo(populate, ALL_KEYS)
    result = guard("check_env_example.py", root)
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")


def test_used_variable_missing_from_example_fails(populate: Populate, guard: Guard) -> None:
    root = repo(populate, ALL_KEYS.replace("GAMMA=\n", ""))
    result = guard("check_env_example.py", root)
    assert result.returncode == 1
    assert result.stderr == "src/gisting/a.py:4: GAMMA is used but missing from .env.example\n"


def test_listed_variable_never_used_fails(populate: Populate, guard: Guard) -> None:
    root = repo(populate, ALL_KEYS + "UNUSED=\n")
    result = guard("check_env_example.py", root)
    assert result.returncode == 1
    assert result.stderr == ".env.example:9: UNUSED is listed but never used\n"


def test_shell_and_typescript_uses_are_detected(populate: Populate, guard: Guard) -> None:
    root = repo(populate, "ALPHA=\nBETA=\nGAMMA=\n")
    result = guard("check_env_example.py", root)
    for name in ("DELTA", "EPSILON", "ZETA", "ETA", "THETA"):
        assert f"{name} is used but missing" in result.stderr


def test_missing_example_file_fails(populate: Populate, guard: Guard) -> None:
    root = repo(populate, None)
    result = guard("check_env_example.py", root)
    assert result.returncode == 1
    assert result.stderr == ".env.example:1: file is missing\n"


def test_tests_and_legacy_do_not_contribute_uses(populate: Populate, guard: Guard) -> None:
    root = populate({
        ".env.example": "ALPHA=\n",
        "src/gisting/a.py": "import os\nos.environ['ALPHA']\n",
        "scripts/tests/t.sh": "#!/usr/bin/env bash\necho $FAKE_ONLY\n",
        "src/gisting/test_b.py": "import os\nos.environ['TEST_ONLY']\n",
        "legacy/x.py": "import os\nos.environ['OLD']\n",
    })
    assert guard("check_env_example.py", root).returncode == 0
