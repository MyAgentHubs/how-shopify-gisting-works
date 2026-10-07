import json
import re
import shutil
import unicodedata
from pathlib import Path

import pytest
from conftest import SCRIPTS_DIR, Guard

REPO = SCRIPTS_DIR.parent
SCRIPT = "check_replay.py"
REPLAY = "apps/gateway/replay.json"
LIMITS = "apps/gateway/limits.json"
RULES = "data/replay/replay-rules-v1.json"
PHRASES = "prompts/reply_phrases.json"
GOOD_EMAIL = "abcdefghij@orders.example.com"


def build(root: Path, turns: list[object], **top: object) -> Path:
    for name in (LIMITS, RULES, PHRASES):
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO / name, root / name)
    document = {"status": "awaiting_user_confirmation", "turns": turns, **top}
    (root / REPLAY).write_text(json.dumps(document), encoding="utf-8")
    return root


def user(content: object) -> dict[str, object]:
    return {"role": "user", "content": content}


def bot(content: object) -> dict[str, object]:
    return {"role": "assistant", "content": content}


def test_the_committed_replay_passes(guard: Guard) -> None:
    result = guard(SCRIPT, REPO)
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")


def test_a_recording_that_is_clean_passes(tmp_path: Path, guard: Guard) -> None:
    turns = [
        user(f"Order #1001, email {GOOD_EMAIL}"),
        bot("Order #1101 shipped, a task-list risk-free."),
        user("x" * 300),
        bot("y" * 400),
    ]
    result = guard(SCRIPT, build(tmp_path, list(turns)))
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")


def examples() -> dict[str, str]:
    phrases = json.loads((REPO / PHRASES).read_text(encoding="utf-8"))
    return phrases["ask_examples"]


def test_the_ask_template_examples_pass_in_an_assistant_turn(tmp_path: Path, guard: Guard) -> None:
    shown = examples()
    text = f"Send order {shown['order_number']} and {shown['email']}"
    result = guard(SCRIPT, build(tmp_path, [bot(text)]))
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")


def test_the_template_examples_follow_the_phrases_file(tmp_path: Path, guard: Guard) -> None:
    root = build(tmp_path, [bot("Send order #1235 and other@example.com")])
    phrases = json.loads((root / PHRASES).read_text(encoding="utf-8"))
    phrases["ask_examples"] = {"order_number": "#1235", "email": "other@example.com"}
    (root / PHRASES).write_text(json.dumps(phrases), encoding="utf-8")
    assert guard(SCRIPT, root).returncode == 0
    (root / PHRASES).write_text(json.dumps({"ask_examples": {}}), encoding="utf-8")
    assert guard(SCRIPT, root).returncode == 1


def test_the_template_examples_are_refused_in_a_user_turn(tmp_path: Path, guard: Guard) -> None:
    shown = examples()
    for text in (shown["order_number"], shown["email"]):
        assert guard(SCRIPT, build(tmp_path, [user(f"hi {text}")])).returncode == 1


BAD_TURNS: dict[str, tuple[list[object], str]] = {
    "role": ([{"role": "system", "content": "hello"}], "role"),
    "extra key": ([{"role": "user", "content": "hi", "name": "x"}], "turn 1"),
    "non-string content": ([user(5)], "content"),
    "empty content": ([user("  ")], "content"),
    "not an object": (["hi"], "turn 1"),
    "canary": ([bot("Your order GLR-DC26C5A7 is here")], "canary"),
    "canary hidden by an escape": ([bot("GLR-DC26C5A7")], "canary"),
    "shopify token": ([bot("token shpat_0123456789abcdef")], "shopify_token"),
    "hugging face token": ([bot("use hf_abcdefghijklmnop")], "hugging_face_token"),
    "api key": ([user("my key sk-abcdefghijklmnop")], "api_key_sk"),
    "github token": ([bot("ghp_abcdefghijklmnopqrstuvwxyz0123456789")], "github_token"),
    "private key": ([bot("-----BEGIN RSA PRIVATE KEY-----")], "private_key"),
    "other domain": ([user("me at abcdefghij@example.com")], "email"),
    "wrong alphabet": ([user("abcdefghi1@orders.example.com")], "email"),
    "too short a name": ([user("abcdefghi@orders.example.com")], "email"),
    "too long a name": ([user("abcdefghijk@orders.example.com")], "email"),
    "upper case name": ([user("ABCDEFGHIJ@orders.example.com")], "email"),
    "long user text": ([user("x" * 301)], "301"),
    "order below range": ([user("Where is #1000")], "#1000"),
    "order above range": ([bot("Order #1102 is late")], "#1102"),
    "order like the template example": ([bot("Order #1235 is late")], "#1235"),
    "email like the template example": ([bot("write other@example.com")], "email"),
}


@pytest.mark.parametrize(("turns", "needle"), BAD_TURNS.values(), ids=BAD_TURNS.keys())
def test_known_bad_recordings_fail(
    tmp_path: Path, guard: Guard, turns: list[object], needle: str
) -> None:
    result = guard(SCRIPT, build(tmp_path, turns))
    assert result.returncode == 1
    assert result.stdout == ""
    assert needle in result.stderr
    assert result.stderr.startswith(f"{REPLAY}:")


def test_a_secret_in_the_status_field_fails(tmp_path: Path, guard: Guard) -> None:
    root = build(tmp_path, [], status="shpat_0123456789abcdef")
    assert guard(SCRIPT, root).returncode == 1


def test_an_unknown_top_level_key_fails(tmp_path: Path, guard: Guard) -> None:
    assert guard(SCRIPT, build(tmp_path, [], extra=1)).returncode == 1


def test_a_missing_turns_list_fails(tmp_path: Path, guard: Guard) -> None:
    root = build(tmp_path, [])
    (root / REPLAY).write_text('{"status": "x"}', encoding="utf-8")
    result = guard(SCRIPT, root)
    assert result.returncode == 1
    assert "turns" in result.stderr


def test_a_file_that_is_not_json_fails(tmp_path: Path, guard: Guard) -> None:
    root = build(tmp_path, [])
    (root / REPLAY).write_text("{nope", encoding="utf-8")
    assert guard(SCRIPT, root).returncode == 1


def test_a_missing_recording_fails(tmp_path: Path, guard: Guard) -> None:
    root = build(tmp_path, [])
    (root / REPLAY).unlink()
    result = guard(SCRIPT, root)
    assert result.returncode == 1
    assert "missing" in result.stderr


def test_the_user_limit_follows_the_gateway_limit(tmp_path: Path, guard: Guard) -> None:
    root = build(tmp_path, [user("x" * 100)])
    limits = json.loads((root / LIMITS).read_text(encoding="utf-8"))
    limits["maxMessageChars"] = 50
    (root / LIMITS).write_text(json.dumps(limits), encoding="utf-8")
    assert guard(SCRIPT, root).returncode == 1


def test_committed_replay_uses_only_public_orders_and_emails() -> None:
    public = json.loads((REPO / "apps/web/data/public_orders.json").read_text())["orders"]
    document = json.loads((REPO / REPLAY).read_text())
    text = unicodedata.normalize("NFKC", json.dumps(document, ensure_ascii=False))
    orders = {"#" + number for number in re.findall(r"(?i)(?:#\s*|\border\s+)([0-9]+)", text)}
    emails = set(re.findall(r"[A-Za-z0-9._%+-]+@orders\.example\.com", text))
    assert orders and orders <= {row["order"] for row in public}
    assert emails and emails <= {row["email"] for row in public}
    plan = json.loads((REPO / "data/demo-orders/shipment-plan-v1.json").read_text())
    entries = {row["order"]: row for row in plan["entries"]}
    assert entries["#1006"]["scenario"] == "IN_TRANSIT"
    assert entries["#1006"]["tracking"]["number"] in text
    assert entries["#1022"]["scenario"] == "UNFULFILLED"
