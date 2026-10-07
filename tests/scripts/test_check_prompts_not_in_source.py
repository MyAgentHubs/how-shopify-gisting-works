from conftest import Guard, Populate

PROMPT_LINE = "You are a careful support agent for Gisting Lab."


def test_passes_when_no_data_directories_exist(populate: Populate, guard: Guard) -> None:
    root = populate({"src/gisting/a.py": f'TEXT = "{PROMPT_LINE}"\n'})
    result = guard("check_prompts_not_in_source.py", root)
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")


def test_passes_when_source_is_clean(populate: Populate, guard: Guard) -> None:
    root = populate({"prompts/rules.md": f"{PROMPT_LINE}\n", "src/gisting/a.py": "x = 1\n"})
    assert guard("check_prompts_not_in_source.py", root).returncode == 0


def test_normalized_match_in_source_fails(populate: Populate, guard: Guard) -> None:
    shouted = "YOU  are a careful\n    SUPPORT agent for gisting lab."
    root = populate({
        "prompts/rules.md": f"{PROMPT_LINE}\n",
        "src/gisting/a.py": f'x = 1\nT = """{shouted}"""\n',
    })
    result = guard("check_prompts_not_in_source.py", root)
    assert result.returncode == 1
    assert result.stderr == "src/gisting/a.py:2: contains data line from prompts/rules.md:1\n"


def test_kb_and_eval_cases_are_data_directories(populate: Populate, guard: Guard) -> None:
    root = populate({
        "kb/returns.md": "Returns are accepted within thirty days.\n",
        "eval/cases/a.jsonl": '{"question": "Where is my parcel right now?"}\n',
        "apps/web/a.ts": "const a = 'returns are accepted within thirty days.';\n",
        "src/gisting/b.py": 'Q = \'{"question": "where is my parcel right now?"}\'\n',
    })
    result = guard("check_prompts_not_in_source.py", root)
    assert result.returncode == 1
    assert "apps/web/a.ts:1:" in result.stderr
    assert "src/gisting/b.py:1:" in result.stderr


def test_lines_shorter_than_20_characters_are_ignored(populate: Populate, guard: Guard) -> None:
    root = populate({"prompts/rules.md": "Be brief.\n", "src/gisting/a.py": "T = 'be brief.'\n"})
    assert guard("check_prompts_not_in_source.py", root).returncode == 0


def test_test_files_are_exempt(populate: Populate, guard: Guard) -> None:
    root = populate({
        "prompts/rules.md": f"{PROMPT_LINE}\n",
        "src/gisting/test_a.py": f'T = "{PROMPT_LINE}"\n',
        "apps/web/a.test.ts": f"const t = '{PROMPT_LINE}';\n",
    })
    assert guard("check_prompts_not_in_source.py", root).returncode == 0
