import pytest
from conftest import Guard, Populate

OK_FILES = {
    "src/a.ts": (
        "// eslint-disable-next-line no-console, @typescript-eslint/no-explicit-any\nconst a = 1;\n"
    ),
    "tests/a.test.ts": "// @ts-expect-error\nconst b: number = 'x';\n",
    "scripts/run.mjs": "#!/usr/bin/env node\nexport const c = 1;\n",
}


def test_ts_allowed_directives_pass(populate: Populate, guard: Guard) -> None:
    result = guard("check_no_comments.py", populate(OK_FILES))
    assert (result.returncode, result.stderr) == (0, "")


def test_comment_markers_inside_strings_and_templates_are_not_comments(
    populate: Populate, guard: Guard
) -> None:
    source = (
        "const a = '/* x */ // y';\n"
        'const b = "// z /*";\n'
        "const c = `// t ${'/*' + `// nested ${1}`} /* u */`;\n"
        "const d = /\\/\\/[/*]/.test('//');\n"
        "const e = 4 / 2 / 1;\n"
        "const f = { g: `${{ h: 1 }.h}` }; // eslint-disable-next-line no-console\n"
    )
    result = guard("check_no_comments.py", populate({"src/a.tsx": source}))
    assert result.returncode == 1
    assert result.stderr == "src/a.tsx:6: comment is not an allowed directive\n"


BAD = {
    "block_disable": "/* eslint-disable */\nconst a = 1;\n",
    "block_disable_rule": "/* eslint-disable no-console */\nconst a = 1;\n",
    "line_disable": "// eslint-disable\nconst a = 1;\n",
    "line_disable_line": "// eslint-disable-line no-console\nconst a = 1;\n",
    "block_enable": "/* eslint-enable */\nconst a = 1;\n",
    "block_next_line": "/* eslint-disable-next-line no-console */\nconst a = 1;\n",
    "nocheck": "// @ts-nocheck\nconst a = 1;\n",
    "ignore": "// @ts-ignore\nconst a = 1;\n",
    "expect_in_src": "// @ts-expect-error\nconst a = 1;\n",
    "prose": "// explain\nconst a = 1;\n",
    "trailing": "const a = 1; // eslint-disable-next-line no-console\n",
    "jsdoc": "const a = 1;\n/** doc */\n",
    "next_line_no_rule": "// eslint-disable-next-line\nconst a = 1;\n",
}


@pytest.mark.parametrize("name", sorted(BAD))
def test_forbidden_ts_comments_fail(populate: Populate, guard: Guard, name: str) -> None:
    result = guard("check_no_comments.py", populate({"src/a.ts": BAD[name]}))
    assert result.returncode == 1
    assert result.stderr.startswith("src/a.ts:")


def test_multiline_block_comment_reports_start_line(populate: Populate, guard: Guard) -> None:
    result = guard("check_no_comments.py", populate({"src/a.mjs": "x;\n/* a\nb\n*/\ny;\n"}))
    assert result.stderr.startswith("src/a.mjs:2:")


def test_ts_generated_node_modules_and_legacy_are_skipped(populate: Populate, guard: Guard) -> None:
    files = {
        "contracts/x.generated.ts": "/* eslint-disable */\n",
        "node_modules/p/a.ts": "// hi\n",
        "legacy/a.mjs": "// hi\n",
        "src/types.d.ts": "// hi\n",
    }
    assert guard("check_no_comments.py", populate(files)).returncode == 0
