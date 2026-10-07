import io
import json
import sys
from pathlib import Path
from typing import Any

import pytest
from tool_support import SECRET, SESSION

from gisting.agent.policy import load_agent_policy
from gisting.prompt.replies import Unrenderable, render_reply
from gisting.shopify.demo_email import demo_email
from gisting.shopify.plan_transport import load_local_source
from gisting.tools.cli import main

PLAN = load_local_source().plan
FIRST = PLAN.entries[0]


@pytest.fixture(autouse=True)
def secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GISTING_EMAIL_SECRET", SECRET)


@pytest.fixture
def empty_env_file(tmp_path: Path) -> Path:
    path = tmp_path / "empty.env"
    path.write_text("")
    return path


def lookup(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    env_file: Path,
    order: str,
    email: str,
) -> tuple[int, dict[str, Any]]:
    document = {"arguments": {"order_number": order, "email": email}, "session_id": SESSION}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(document)))
    code = main(["call", "lookup_order", "--transport", "local", "--env-file", str(env_file)])
    return code, json.loads(capsys.readouterr().out)


def test_the_local_source_answers_a_lookup_without_any_network(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], empty_env_file: Path
) -> None:
    email = demo_email(SECRET, FIRST.order)
    code, document = lookup(monkeypatch, capsys, empty_env_file, FIRST.order, email)
    assert code == 0
    assert document["result"]["status"] == "found"
    assert document["result"]["order"]["canary"]["value"] == FIRST.canary


def test_the_local_source_still_requires_the_matching_email(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], empty_env_file: Path
) -> None:
    other = demo_email(SECRET, PLAN.entries[1].order)
    code, document = lookup(monkeypatch, capsys, empty_env_file, FIRST.order, other)
    assert code == 0
    assert document["result"] == {"status": "no_match"}
    assert FIRST.canary not in json.dumps(document)


def test_every_plan_order_renders_into_a_reply(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], empty_env_file: Path
) -> None:
    phrases = load_agent_policy().answers.phrases
    for entry in PLAN.entries:
        email = demo_email(SECRET, entry.order)
        _, document = lookup(monkeypatch, capsys, empty_env_file, entry.order, email)
        reply = render_reply(phrases, document["result"])
        assert not isinstance(reply, Unrenderable), entry.order
