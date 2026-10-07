import io
from pathlib import Path

import pytest
from fakes.shopify import FakeTransport
from loading_support import CANARY, environ_in
from runner_support import lookup_parts

from gisting.serve.__main__ import Hooks
from gisting.serve.config import LIMITS, ConfigError, ServeEnv, load_env

EMAIL_VARIABLE = "GISTING_EMAIL_SECRET"
LONG_ENOUGH = "e" * LIMITS.min_secret_chars


def failure_with(tmp_path: Path, value: str) -> ConfigError:
    with pytest.raises(ConfigError) as caught:
        load_env({**environ_in(tmp_path), EMAIL_VARIABLE: value})
    return caught.value


def test_an_email_secret_of_exactly_the_minimum_length_is_accepted(tmp_path: Path) -> None:
    env = load_env({**environ_in(tmp_path), EMAIL_VARIABLE: LONG_ENOUGH})
    assert env.email_secret == LONG_ENOUGH


@pytest.mark.parametrize(
    "value",
    [
        "",
        "   ",
        "x",
        "e" * (LIMITS.min_secret_chars - 1),
        " " + LONG_ENOUGH,
        LONG_ENOUGH + "\n",
        "e" * 20 + "\t" + "e" * 20,
        "sécret" + LONG_ENOUGH,
    ],
)
def test_a_weak_email_secret_is_refused_by_name_without_echoing_it(
    tmp_path: Path, value: str
) -> None:
    error = failure_with(tmp_path, value)
    assert error.variables == (EMAIL_VARIABLE,)
    assert str(error).startswith(EMAIL_VARIABLE)
    assert not value.strip() or value not in str(error)


def test_the_email_rule_is_the_one_the_upstream_secret_follows(tmp_path: Path) -> None:
    error = failure_with(tmp_path, "short")
    assert str(LIMITS.min_secret_chars) in str(error)


def test_the_environment_record_hides_every_secret_from_its_repr(tmp_path: Path) -> None:
    env = ServeEnv(
        8123, f"{CANARY}-up", f"{CANARY}-mail", f"{CANARY}-shop", tmp_path, tmp_path, None
    )
    assert CANARY not in repr(env)
    assert "8123" in repr(env)


def test_the_lookup_parts_hide_the_email_secret_from_their_repr() -> None:
    parts = lookup_parts(FakeTransport([]))
    assert parts.email_secret not in repr(parts)


def test_the_hooks_hide_the_environment_from_their_repr() -> None:
    hooks = Hooks({"SHOPIFY_CLIENT_SECRET": f"{CANARY}-shop"}, io.StringIO())
    assert CANARY not in repr(hooks)
