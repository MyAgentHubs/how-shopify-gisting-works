from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parents[3] / "prompts"
TOOLS_DIR = PROMPTS_DIR / "tools"


def read_prompt(name: str) -> str:
    return (PROMPTS_DIR / name).read_text(encoding="utf-8").removesuffix("\n")
