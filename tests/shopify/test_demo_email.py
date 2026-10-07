import base64
import hashlib
import hmac
import os
from pathlib import Path

import pytest

from gisting.shopify.demo_email import MissingSecret, demo_email, email_secret
from gisting.shopify.env_file import load_env_file

SECRET = "unit-test-secret"


def test_email_is_lowercase_base32_hmac_prefix() -> None:
    digest = hmac.new(SECRET.encode(), b"#1042", hashlib.sha256).digest()
    expected = base64.b32encode(digest).decode().lower()[:10]
    assert demo_email(SECRET, "#1042") == f"{expected}@orders.example.com"


def test_email_is_reproducible_and_accepts_bare_number() -> None:
    assert demo_email(SECRET, "1042") == demo_email(SECRET, "#1042")


def test_distinct_orders_get_distinct_emails() -> None:
    emails = {demo_email(SECRET, f"#{number}") for number in range(1002, 1102)}
    assert len(emails) == 100


def test_secret_changes_the_email() -> None:
    assert demo_email(SECRET, "#1042") != demo_email("other", "#1042")


def test_missing_secret_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GISTING_EMAIL_SECRET", "placeholder")
    monkeypatch.delenv("GISTING_EMAIL_SECRET")
    with pytest.raises(MissingSecret):
        email_secret()


def test_empty_secret_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GISTING_EMAIL_SECRET", "")
    with pytest.raises(MissingSecret):
        email_secret()


def test_env_file_fills_missing_keys_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GISTING_EMAIL_SECRET", "placeholder")
    monkeypatch.delenv("GISTING_EMAIL_SECRET")
    monkeypatch.setenv("GISTING_KEPT", "from-env")
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# note\nGISTING_EMAIL_SECRET='quoted value'\nexport GISTING_KEPT=from-file\n\nbad line\n"
    )
    assert load_env_file(env_file) is True
    assert email_secret() == "quoted value"
    assert os.environ["GISTING_KEPT"] == "from-env"


def test_missing_env_file_reports_false(tmp_path: Path) -> None:
    assert load_env_file(tmp_path / "absent.env") is False
