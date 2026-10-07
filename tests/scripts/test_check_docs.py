import pytest
from conftest import Guard, Populate

HANDOFF_LIMIT = 300
DESIGN_LIMIT = 400
DECISION_LIMIT = 60


def doc(kind: str, extra: str = "", status: str = "current", body_lines: int = 1) -> str:
    head = (
        f"---\ntype: {kind}\nstatus: {status}\nupdated: 2026-10-02\nsummary: one line\n{extra}---\n"
    )
    return head + "body\n" * body_lines


def index(*names: str) -> str:
    return "# Index\n\n" + "".join(f"- [{name}]({name}) - one line\n" for name in names)


def valid_repo(populate: Populate) -> dict[str, str]:
    return {
        "docs/README.md": "# Docs\n",
        "docs/handoff.md": doc("handoff"),
        "docs/decisions/0001-a.md": doc("decision"),
        "docs/decisions/INDEX.md": index("0001-a.md"),
        "docs/design/agent.md": doc("design"),
        "docs/design/INDEX.md": index("agent.md"),
        "docs/learning/runs/2026-10-02-r1.md": doc("run"),
        "docs/learning/runs/INDEX.md": index("2026-10-02-r1.md"),
        "docs/learning/concepts/cache.md": doc("concept"),
        "docs/learning/concepts/INDEX.md": index("cache.md"),
    }


def messages(populate: Populate, guard: Guard, files: dict[str, str]) -> tuple[int, str]:
    result = guard("check_docs.py", populate(files))
    return result.returncode, result.stderr


def test_a_governed_docs_tree_passes(populate: Populate, guard: Guard) -> None:
    root = populate(valid_repo(populate))
    result = guard("check_docs.py", root)
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")


def test_a_repo_without_docs_passes(populate: Populate, guard: Guard) -> None:
    assert messages(populate, guard, {"src/a.py": "x = 1\n"}) == (0, "")


def test_missing_front_matter_fails(populate: Populate, guard: Guard) -> None:
    files = valid_repo(populate) | {"docs/design/agent.md": "# no front matter\n"}
    code, err = messages(populate, guard, files)
    assert code == 1
    assert "docs/design/agent.md:1: front matter is missing" in err


def test_incomplete_front_matter_names_each_missing_field(populate: Populate, guard: Guard) -> None:
    text = "---\ntype: design\nstatus: current\n---\nbody\n"
    code, err = messages(populate, guard, valid_repo(populate) | {"docs/design/agent.md": text})
    assert code == 1
    assert "front matter is missing updated" in err
    assert "front matter is missing summary" in err


def test_invalid_status_and_date_fail(populate: Populate, guard: Guard) -> None:
    text = doc("design", status="draft").replace("2026-10-02", "yesterday")
    code, err = messages(populate, guard, valid_repo(populate) | {"docs/design/agent.md": text})
    assert code == 1
    assert "status draft is not current|superseded" in err
    assert "updated must be YYYY-MM-DD" in err


def test_type_must_match_the_directory(populate: Populate, guard: Guard) -> None:
    files = valid_repo(populate) | {"docs/design/agent.md": doc("run")}
    code, err = messages(populate, guard, files)
    assert code == 1
    assert "type run must be design here" in err


def test_line_limits_apply_per_type(populate: Populate, guard: Guard) -> None:
    files = valid_repo(populate) | {
        "docs/decisions/0001-a.md": doc("decision", body_lines=DECISION_LIMIT),
        "docs/design/agent.md": doc("design", body_lines=DESIGN_LIMIT),
        "docs/handoff.md": doc("handoff", body_lines=HANDOFF_LIMIT),
    }
    code, err = messages(populate, guard, files)
    assert code == 1
    assert "decision has 66 lines (max 60)" in err
    assert "design has 406 lines (max 400)" in err
    assert "handoff has 306 lines (max 300)" in err


def test_a_document_at_its_limit_passes(populate: Populate, guard: Guard) -> None:
    files = valid_repo(populate) | {"docs/design/agent.md": doc("design", body_lines=394)}
    assert messages(populate, guard, files) == (0, "")


def test_unlisted_file_fails(populate: Populate, guard: Guard) -> None:
    files = valid_repo(populate) | {"docs/design/models.md": doc("design")}
    code, err = messages(populate, guard, files)
    assert code == 1
    assert "docs/design/INDEX.md:1: models.md is not listed" in err


def test_index_entry_for_a_missing_file_fails(populate: Populate, guard: Guard) -> None:
    files = valid_repo(populate) | {"docs/design/INDEX.md": index("agent.md", "gone.md")}
    code, err = messages(populate, guard, files)
    assert code == 1
    assert "docs/design/INDEX.md:1: gone.md does not exist" in err


def test_directory_without_an_index_fails(populate: Populate, guard: Guard) -> None:
    files = valid_repo(populate)
    del files["docs/decisions/INDEX.md"]
    code, err = messages(populate, guard, files)
    assert code == 1
    assert "docs/decisions:1: INDEX.md is missing" in err


def test_superseded_needs_an_existing_superseded_by(populate: Populate, guard: Guard) -> None:
    base = valid_repo(populate)
    bare = base | {"docs/decisions/0001-a.md": doc("decision", status="superseded")}
    assert "superseded document needs superseded_by" in messages(populate, guard, bare)[1]


def test_superseded_by_must_point_to_an_existing_file(populate: Populate, guard: Guard) -> None:
    missing = valid_repo(populate) | {
        "docs/decisions/0001-a.md": doc(
            "decision", "superseded_by: docs/decisions/0002-b.md\n", "superseded"
        )
    }
    assert (
        "superseded_by docs/decisions/0002-b.md does not exist"
        in messages(populate, guard, missing)[1]
    )


def test_superseded_with_an_existing_target_passes(populate: Populate, guard: Guard) -> None:
    files = valid_repo(populate) | {
        "docs/decisions/0001-a.md": doc(
            "decision", "superseded_by: docs/decisions/0002-b.md\n", "superseded"
        ),
        "docs/decisions/0002-b.md": doc("decision"),
        "docs/decisions/INDEX.md": index("0001-a.md", "0002-b.md"),
    }
    assert messages(populate, guard, files) == (0, "")


def test_docs_root_allows_only_readme_and_handoff(populate: Populate, guard: Guard) -> None:
    files = valid_repo(populate) | {"docs/notes.md": doc("concept")}
    code, err = messages(populate, guard, files)
    assert code == 1
    assert "docs/notes.md:1: docs root allows only README.md and handoff.md" in err


def test_html_under_docs_fails(populate: Populate, guard: Guard) -> None:
    files = valid_repo(populate) | {"docs/design/agent.html": "<html></html>\n"}
    code, err = messages(populate, guard, files)
    assert code == 1
    assert "docs/design/agent.html:1: docs must not contain generated HTML" in err


def test_markdown_in_an_ungoverned_directory_fails(populate: Populate, guard: Guard) -> None:
    files = valid_repo(populate) | {
        "docs/misc/a.md": doc("concept"),
        "docs/misc/INDEX.md": index("a.md"),
    }
    code, err = messages(populate, guard, files)
    assert code == 1
    assert "docs/misc/a.md:1: misc is not a governed docs directory" in err


@pytest.mark.parametrize("body_lines", [1, 194])
def test_guides_with_metadata_and_index_pass(
    populate: Populate, guard: Guard, body_lines: int
) -> None:
    files = {
        "docs/guides/architecture.md": doc("guide", body_lines=body_lines),
        "docs/guides/INDEX.md": index("architecture.md"),
    }
    assert messages(populate, guard, files) == (0, "")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("# Guide\n", "front matter is missing"),
        ("---\ntype: guide\n---\n", "front matter is missing status"),
        (doc("design"), "type design must be guide here"),
        (doc("guide", status="draft"), "status draft is not current|superseded"),
        (doc("guide").replace("2026-10-02", "today"), "updated must be YYYY-MM-DD"),
        (doc("guide", body_lines=195), "guide has 201 lines (max 200)"),
    ],
)
def test_invalid_guides_fail(populate: Populate, guard: Guard, text: str, expected: str) -> None:
    files = {
        "docs/guides/architecture.md": text,
        "docs/guides/INDEX.md": index("architecture.md"),
    }
    code, err = messages(populate, guard, files)
    assert code == 1
    assert expected in err


@pytest.mark.parametrize("field", ["type", "status", "updated", "summary"])
def test_guides_require_each_metadata_field(populate: Populate, guard: Guard, field: str) -> None:
    text = "\n".join(line for line in doc("guide").splitlines() if not line.startswith(field + ":"))
    files = {
        "docs/guides/architecture.md": text,
        "docs/guides/INDEX.md": index("architecture.md"),
    }
    code, err = messages(populate, guard, files)
    assert code == 1
    assert f"front matter is missing {field}" in err


@pytest.mark.parametrize(
    ("listing", "expected"),
    [
        (None, "docs/guides:1: INDEX.md is missing"),
        (index(), "docs/guides/INDEX.md:1: architecture.md is not listed"),
        (index("architecture.md", "gone.md"), "docs/guides/INDEX.md:1: gone.md does not exist"),
    ],
)
def test_guides_require_a_complete_existing_index(
    populate: Populate, guard: Guard, listing: str | None, expected: str
) -> None:
    files = {"docs/guides/architecture.md": doc("guide")}
    if listing is not None:
        files["docs/guides/INDEX.md"] = listing
    code, err = messages(populate, guard, files)
    assert code == 1
    assert expected in err
