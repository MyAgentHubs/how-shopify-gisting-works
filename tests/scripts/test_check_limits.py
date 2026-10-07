from conftest import Guard, Populate

FILE_LIMIT = 300
FUNCTION_LIMIT = 50


def function_with(lines: int) -> str:
    body = "\n".join("    value = 1" for _ in range(lines - 1))
    return f"def work() -> None:\n{body}\n"


def lines_of(count: int) -> str:
    return "\n".join(f"value_{index} = {index}" for index in range(count)) + "\n"


def test_small_files_pass(populate: Populate, guard: Guard) -> None:
    root = populate({"src/gisting/a.py": function_with(FUNCTION_LIMIT), "apps/web/a.ts": "x\n"})
    result = guard("check_limits.py", root)
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")


def test_function_of_51_lines_fails(populate: Populate, guard: Guard) -> None:
    root = populate({"src/gisting/a.py": function_with(FUNCTION_LIMIT + 1)})
    result = guard("check_limits.py", root)
    assert result.returncode == 1
    assert result.stderr.startswith("src/gisting/a.py:1: function work has 51 non-blank lines")


def test_blank_lines_do_not_count_toward_function_size(populate: Populate, guard: Guard) -> None:
    spaced = function_with(FUNCTION_LIMIT).replace("    value = 1\n", "    value = 1\n\n")
    root = populate({"src/gisting/a.py": spaced})
    assert guard("check_limits.py", root).returncode == 0


def test_python_file_of_301_lines_fails(populate: Populate, guard: Guard) -> None:
    root = populate({"src/gisting/big.py": lines_of(FILE_LIMIT + 1)})
    result = guard("check_limits.py", root)
    assert result.returncode == 1
    assert "src/gisting/big.py:1: file has 301 non-blank lines" in result.stderr


def test_python_file_of_300_lines_passes(populate: Populate, guard: Guard) -> None:
    root = populate({"src/gisting/big.py": lines_of(FILE_LIMIT) + "\n\n"})
    assert guard("check_limits.py", root).returncode == 0


def test_typescript_and_mjs_files_are_limited(populate: Populate, guard: Guard) -> None:
    root = populate({
        "apps/web/a.ts": lines_of(FILE_LIMIT + 1),
        "apps/web/b.mjs": lines_of(FILE_LIMIT + 1),
    })
    result = guard("check_limits.py", root)
    assert result.returncode == 1
    assert "apps/web/a.ts:1:" in result.stderr
    assert "apps/web/b.mjs:1:" in result.stderr


def test_test_files_are_exempt_from_function_length(populate: Populate, guard: Guard) -> None:
    root = populate({"tests/test_a.py": function_with(FUNCTION_LIMIT + 20)})
    assert guard("check_limits.py", root).returncode == 0


def test_legacy_and_generated_files_are_excluded(populate: Populate, guard: Guard) -> None:
    root = populate({
        "legacy/old.py": lines_of(FILE_LIMIT + 50),
        "shopify-app/x.mjs": lines_of(FILE_LIMIT + 50),
        "apps/web/generated/types.ts": lines_of(FILE_LIMIT + 50),
        "apps/web/api.d.ts": lines_of(FILE_LIMIT + 50),
    })
    assert guard("check_limits.py", root).returncode == 0
