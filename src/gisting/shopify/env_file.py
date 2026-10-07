import os
from pathlib import Path

DEFAULT_ENV_FILE = Path("~/.config/gisting-lab/.env")
QUOTES = "'\""


def parse_line(line: str) -> tuple[str, str] | None:
    text = line.strip().removeprefix("export ")
    key, separator, value = text.partition("=")
    if text.startswith("#") or not separator or not key.strip():
        return None
    return key.strip(), value.strip().strip(QUOTES)


def load_env_file(path: Path) -> bool:
    target = path.expanduser()
    if not target.is_file():
        return False
    for line in target.read_text(encoding="utf-8").splitlines():
        pair = parse_line(line)
        if pair is not None:
            os.environ.setdefault(*pair)
    return True
