from conftest import Guard, Populate

PYPROJECT = (
    '[project]\nname = "x"\nversion = "0"\ndependencies = ["Requests>=2", "typing_extensions==4"]\n'
    '[dependency-groups]\ndev = ["ruff==0.1", {include-group = "other"}]\nother = []\n'
)


def registry(*entries: tuple[str, str]) -> str:
    blocks = [f'[[dependency]]\nname = "{name}"\nreason = "{reason}"\n' for name, reason in entries]
    return "\n".join(blocks)


def test_every_dependency_listed_with_reason_passes(populate: Populate, guard: Guard) -> None:
    deps = registry(("requests", "http"), ("typing-extensions", "types"), ("ruff", "lint"))
    root = populate({"pyproject.toml": PYPROJECT, "deps.toml": deps})
    result = guard("check_deps.py", root)
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")


def test_dependency_missing_from_registry_fails(populate: Populate, guard: Guard) -> None:
    deps = registry(("requests", "http"), ("ruff", "lint"))
    root = populate({"pyproject.toml": PYPROJECT, "deps.toml": deps})
    result = guard("check_deps.py", root)
    assert result.returncode == 1
    assert "typing-extensions is not listed in deps.toml" in result.stderr


def test_empty_reason_fails(populate: Populate, guard: Guard) -> None:
    deps = registry(("requests", "http"), ("typing-extensions", "  "), ("ruff", "lint"))
    root = populate({"pyproject.toml": PYPROJECT, "deps.toml": deps})
    result = guard("check_deps.py", root)
    assert result.returncode == 1
    assert "deps.toml:6: dependency typing-extensions has an empty reason" in result.stderr


def test_missing_reason_key_fails(populate: Populate, guard: Guard) -> None:
    deps = '[[dependency]]\nname = "ruff"\n'
    root = populate({"pyproject.toml": PYPROJECT.replace('"Requests>=2", ', ""), "deps.toml": deps})
    assert guard("check_deps.py", root).returncode == 1


def test_missing_registry_file_fails(populate: Populate, guard: Guard) -> None:
    root = populate({"pyproject.toml": PYPROJECT})
    result = guard("check_deps.py", root)
    assert result.returncode == 1
    assert result.stderr == "deps.toml:1: file is missing\n"


PACKAGE_JSON = (
    '{"name": "x", "dependencies": {"left-pad": "1.0.0"},'
    ' "devDependencies": {"@scope/Types": "2.0.0", "vitest": "3.0.0"}}'
)
PYTHON_ONLY = '[project]\nname = "x"\nversion = "0"\n'


def test_package_json_dependencies_must_be_listed(populate: Populate, guard: Guard) -> None:
    deps = registry(("left-pad", "pad"), ("vitest", "tests"))
    root = populate({
        "pyproject.toml": PYTHON_ONLY,
        "deps.toml": deps,
        "package.json": PACKAGE_JSON,
    })
    result = guard("check_deps.py", root)
    assert result.returncode == 1
    assert "package.json:1: dependency @scope/types is not listed in deps.toml" in result.stderr
    assert "left-pad" not in result.stderr
    assert "vitest" not in result.stderr


def test_listed_package_json_dependencies_pass(populate: Populate, guard: Guard) -> None:
    deps = registry(("left-pad", "pad"), ("@scope/types", "types"), ("vitest", "tests"))
    root = populate({
        "pyproject.toml": PYTHON_ONLY,
        "deps.toml": deps,
        "package.json": PACKAGE_JSON,
    })
    result = guard("check_deps.py", root)
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")


def test_workspace_package_json_is_checked_too(populate: Populate, guard: Guard) -> None:
    files = {
        "pyproject.toml": PYTHON_ONLY,
        "deps.toml": registry(),
        "apps/gateway/package.json": '{"dependencies": {"hono": "4.0.0"}}',
    }
    result = guard("check_deps.py", populate(files))
    assert "apps/gateway/package.json:1: dependency hono is not listed" in result.stderr
