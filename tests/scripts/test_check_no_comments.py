import subprocess

from conftest import Guard, Populate

SEE_TARGET = {"docs/decisions/0001-no-comments.md": "x\n"}


def run(
    populate: Populate, guard: Guard, files: dict[str, str], *extra: str
) -> "subprocess.CompletedProcess[str]":
    return guard("check_no_comments.py", populate(files), *extra)


def test_allowed_directives_pass_and_are_counted(populate: Populate, guard: Guard) -> None:
    source = (
        "#!/usr/bin/env python3\n"
        "import os  # noqa: F401\n"
        "# noqa: E501, F401\n"
        "value: int = 1  # type: ignore[assignment]\n"
        "other = 2  # pyright: ignore[reportAssignmentType]\n"
        "# see: docs/decisions/0001-no-comments.md\n"
    )
    result = run(populate, guard, {"src/gisting/a.py": source, **SEE_TARGET}, "--count")
    assert (result.returncode, result.stdout, result.stderr) == (0, "5\n", "")


def test_silent_on_success(populate: Populate, guard: Guard) -> None:
    result = run(populate, guard, {"src/gisting/a.py": "value = '# not a comment'\n"})
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")


def test_prose_after_noqa_fails(populate: Populate, guard: Guard) -> None:
    result = run(populate, guard, {"src/a.py": "import os  # noqa: F401 unused on purpose\n"})
    assert result.returncode == 1
    assert result.stderr.startswith("src/a.py:1: comment is not an allowed directive")


def test_plain_comment_fails(populate: Populate, guard: Guard) -> None:
    result = run(populate, guard, {"src/a.py": "x = 1\n# explain x\n"})
    assert result.returncode == 1
    assert "src/a.py:2:" in result.stderr


def test_shebang_is_only_allowed_on_first_line(populate: Populate, guard: Guard) -> None:
    result = run(populate, guard, {"src/a.py": "x = 1\n#!/usr/bin/env python3\n"})
    assert result.returncode == 1


def test_docstrings_fail(populate: Populate, guard: Guard) -> None:
    source = (
        '"""module"""\n\n\ndef f() -> None:\n    """function"""\n\n\nclass C:\n    """class"""\n'
    )
    result = run(populate, guard, {"src/a.py": source})
    assert result.returncode == 1
    assert result.stderr.count("docstring is not allowed") == 3


def test_bare_string_statement_fails(populate: Populate, guard: Guard) -> None:
    result = run(populate, guard, {"src/a.py": "x = 1\n'note to self'\n"})
    assert result.returncode == 1
    assert "src/a.py:2: bare string statement is not allowed" in result.stderr


def test_see_pointer_must_name_an_existing_decision(populate: Populate, guard: Guard) -> None:
    result = run(populate, guard, {"src/a.py": "# see: docs/decisions/0009-missing.md\n"})
    assert result.returncode == 1
    assert "target does not exist" in result.stderr


def test_see_pointer_with_wrong_shape_fails(populate: Populate, guard: Guard) -> None:
    files = {"src/a.py": "# see: README.md\n", **SEE_TARGET}
    assert run(populate, guard, files).returncode == 1


def test_legacy_is_not_scanned(populate: Populate, guard: Guard) -> None:
    result = run(populate, guard, {"legacy/old.py": "# anything\n'''doc'''\n"})
    assert result.returncode == 0


def test_shell_allows_shebang_and_shellcheck_directive(populate: Populate, guard: Guard) -> None:
    script = "#!/usr/bin/env bash\n# shellcheck disable=SC2034\nname=1\n"
    result = run(populate, guard, {"scripts/a.sh": script}, "--count")
    assert (result.returncode, result.stdout) == (0, "1\n")


def test_shell_comment_fails_even_when_trailing(populate: Populate, guard: Guard) -> None:
    result = run(populate, guard, {"scripts/a.sh": "#!/usr/bin/env bash\necho hi # greet\n"})
    assert result.returncode == 1
    assert "scripts/a.sh:2: comment is not allowed" in result.stderr


def test_shell_hash_inside_words_quotes_and_heredocs_is_not_a_comment(
    populate: Populate, guard: Guard
) -> None:
    script = (
        "#!/usr/bin/env bash\n"
        'echo "$#" "${#name}" \'a # b\' "x # y" a\\#b\n'
        "cat <<EOF\n# inside heredoc\nEOF\n"
        "cat <<<'# here string'\n"
    )
    assert run(populate, guard, {"scripts/a.sh": script}).returncode == 0


def test_githooks_are_checked_like_shell(populate: Populate, guard: Guard) -> None:
    result = run(populate, guard, {".githooks/pre-push": "#!/usr/bin/env bash\n# run checks\n"})
    assert result.returncode == 1


def test_shell_directive_may_be_indented_but_not_trailing(populate: Populate, guard: Guard) -> None:
    indented = "#!/usr/bin/env bash\nf() {\n  # shellcheck disable=SC2034\n  name=1\n}\n"
    assert run(populate, guard, {"scripts/a.sh": indented}).returncode == 0
    trailing = "#!/usr/bin/env bash\nname=1 # shellcheck disable=SC2034\n"
    assert run(populate, guard, {"scripts/b.sh": trailing}).returncode == 1
