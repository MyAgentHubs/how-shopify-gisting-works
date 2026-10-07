import json
import subprocess
from pathlib import Path

from fakes.case_support import amend_many

PLAN = Path(__file__).resolve().parents[2] / "data" / "demo-orders" / "shipment-plan-v1.json"
IDENTITY = ("-c", "user.name=tester", "-c", "user.email=tester@example.com")


def case_line(**changes: object) -> str:
    return json.dumps(amend_many({key.replace("__", "."): v for key, v in changes.items()}))


def git(root: Path, *args: str) -> str:
    command = ["git", *IDENTITY, "-c", "commit.gpgsign=false", "-C", str(root), *args]
    return subprocess.run(command, capture_output=True, text=True, check=True).stdout.strip()


def put(root: Path, relative: str, *lines: str) -> None:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")


def seed_plan(root: Path) -> None:
    target = root / "data" / "demo-orders" / PLAN.name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(PLAN.read_text(encoding="utf-8"), encoding="utf-8")


def commit(root: Path, message: str = "step") -> str:
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", message)
    return git(root, "rev-parse", "HEAD")


def init_repo(root: Path) -> None:
    git(root, "init", "-q", "-b", "main")
    seed_plan(root)
    put(root, "eval/cases/dev/other_order_probe.jsonl", case_line(), case_line(id="second_case"))
    commit(root, "first")


def user_text_line(body: str, **changes: object) -> str:
    message: list[dict[str, object]] = [{"role": "user", "content": body, "tool_calls": []}]
    return case_line(messages=message, **changes)
