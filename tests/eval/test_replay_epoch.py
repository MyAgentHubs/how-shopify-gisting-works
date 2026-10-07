import ast
from pathlib import Path

import pytest
from fakes.tokenizer import synthetic_prompt_tokenizer

from gisting.eval.replay_epoch import crossed_epoch, epoch_paths, previous_labels
from gisting.eval.report import RULES_VERSION_CHARS
from gisting.prompt.assemble import assemble, full_rules, tools_segment
from gisting.prompt.fingerprint import rules_sha256
from gisting.prompt.messages import UserMessage
from gisting.prompt.schema import load_tool_schemas
from gisting.shopify.jsonvalue import JsonObject

ROOT = Path(__file__).resolve().parents[2]
PROMPT_PACKAGE = "gisting.prompt"
REPLAY_ENTRY_MODULES = ("assemble", "messages", "schema", "segments", "tokenizer")
STORED: JsonObject = {"run": {"rules_version": "feedfeedfeedfeed"}}


def prompt_source(module: str) -> Path:
    return ROOT / "src" / "gisting" / "prompt" / f"{module}.py"


def imported_prompt_modules(module: str) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(prompt_source(module).read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.module == PROMPT_PACKAGE:
            found |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and (node.module or "").startswith(PROMPT_PACKAGE):
            found.add((node.module or "").split(".")[-1])
    return found


def import_closure() -> set[str]:
    pending: list[str] = list(REPLAY_ENTRY_MODULES)
    seen: set[str] = set()
    while pending:
        module = pending.pop()
        if module not in seen:
            seen.add(module)
            pending += imported_prompt_modules(module)
    return seen


def listed_sources() -> set[str]:
    prefix = "src/gisting/prompt/"
    return {
        item.removeprefix(prefix).removesuffix(".py")
        for item in epoch_paths()
        if item.startswith(prefix)
    }


def expand(listed: str) -> set[str]:
    target = ROOT / listed
    if target.is_dir():
        return {path.relative_to(ROOT).as_posix() for path in target.rglob("*") if path.is_file()}
    return {listed}


def read_by_the_replay(monkeypatch: pytest.MonkeyPatch) -> set[str]:
    seen: set[str] = set()
    original = Path.read_text

    def spy(self: Path, encoding: str | None = None) -> str:
        seen.add(self.resolve().relative_to(ROOT).as_posix())
        return original(self, encoding=encoding)

    monkeypatch.setattr(Path, "read_text", spy)
    tokenizer = synthetic_prompt_tokenizer()
    rules = full_rules(tokenizer)
    tools = tools_segment(tokenizer, load_tool_schemas().values())
    assemble(tokenizer, rules, tools, [UserMessage("hello")])
    return {item for item in seen if item.startswith("prompts/")}


def test_the_epoch_sources_are_exactly_the_prompt_modules_the_replay_imports() -> None:
    assert listed_sources() == import_closure()


def test_the_epoch_prompt_files_are_exactly_the_files_the_replay_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    listed = {
        path for item in epoch_paths() if item.startswith("prompts/") for path in expand(item)
    }
    assert listed == read_by_the_replay(monkeypatch)


def test_every_epoch_path_exists_and_files_the_replay_ignores_are_absent() -> None:
    assert all((ROOT / item).exists() for item in epoch_paths())
    assert not any(
        "agent_policy" in item or item.startswith(("src/gisting/agent", "src/gisting/tools"))
        for item in epoch_paths()
    )


OLDER_LABEL = sorted(previous_labels())[0]
OLDER_EPOCH: JsonObject = {"run": {"rules_version": OLDER_LABEL}}
UNREACHABLE = (
    (Path("/nonexistent"), "a" * 40),
    (ROOT, "0" * 40),
    (ROOT, "HEAD"),
    (ROOT, ""),
)


def test_every_previous_rules_file_has_a_distinct_label_that_is_not_the_current_one() -> None:
    files = list((ROOT / "data" / "eval" / "previous_rules").glob("*.md"))
    assert len(previous_labels()) == len(files) > 1
    assert rules_sha256()[:RULES_VERSION_CHARS] not in previous_labels()


@pytest.mark.parametrize(("root", "tree"), UNREACHABLE)
def test_an_unreachable_tree_with_a_previous_rules_version_is_a_different_epoch(
    root: Path, tree: str
) -> None:
    assert crossed_epoch(root, tree, OLDER_EPOCH) is not None


@pytest.mark.parametrize(("root", "tree"), UNREACHABLE)
def test_an_unreachable_tree_with_the_current_rules_version_is_replayed(
    root: Path, tree: str
) -> None:
    current: JsonObject = {"run": {"rules_version": rules_sha256()[:RULES_VERSION_CHARS]}}
    assert crossed_epoch(root, tree, current) is None


@pytest.mark.parametrize(
    "stored",
    [STORED, {}, {"run": {}}, {"run": {"rules_version": 7}}, {"run": {"rules_version": ""}}],
)
def test_an_unreachable_tree_with_an_unknown_or_missing_rules_version_is_replayed(
    stored: JsonObject,
) -> None:
    assert crossed_epoch(ROOT, "0" * 40, stored) is None


@pytest.mark.parametrize("text", ['{"paths": []}', '{"paths": [""]}', '{"paths": [1]}', "{}"])
def test_an_epoch_file_without_real_paths_is_refused(tmp_path: Path, text: str) -> None:
    path = tmp_path / "epoch.json"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError):
        epoch_paths(path)
