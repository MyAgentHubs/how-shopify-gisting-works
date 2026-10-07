import os
from pathlib import Path

import pytest
from loading_support import CANARY, environ_in
from startup_support import never_lookup, never_models, new_run, port_is_free

import gisting.serve.config as config_module
from gisting.serve.config import ConfigError, load_env

LONG_PORT = "9" * 5000


def failure_of(environ: dict[str, str]) -> ConfigError:
    with pytest.raises(ConfigError) as caught:
        load_env(environ)
    return caught.value


def test_an_endless_port_names_its_variable_and_never_echoes_the_digits(tmp_path: Path) -> None:
    error = failure_of({**environ_in(tmp_path), "GISTING_SERVE_PORT": LONG_PORT})
    assert error.variables == ("GISTING_SERVE_PORT",)
    assert str(error) == "GISTING_SERVE_PORT must be an integer from 1 to 65535"


def test_an_unknown_user_home_in_a_directory_variable_names_the_variable(tmp_path: Path) -> None:
    error = failure_of({**environ_in(tmp_path), "GISTING_MODEL_DIR": "~nouser-4c1e/models"})
    assert error.variables == ("GISTING_MODEL_DIR",)
    assert str(error) == "GISTING_MODEL_DIR must name an existing directory"


@pytest.mark.skipif(os.geteuid() == 0, reason="root can enter any directory")
def test_a_directory_behind_a_locked_parent_names_the_variable(tmp_path: Path) -> None:
    locked = tmp_path / "locked"
    (locked / "inner").mkdir(parents=True)
    locked.chmod(0)
    try:
        error = failure_of({**environ_in(tmp_path), "GISTING_GIST_DIR": str(locked / "inner")})
    finally:
        locked.chmod(0o700)
    assert error.variables == ("GISTING_GIST_DIR",)
    assert str(error) == "GISTING_GIST_DIR must name an existing directory"


def test_an_unforeseen_reader_error_still_names_its_variable_and_only_its_type(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(_environ: object) -> str:
        message = f"{CANARY} private"
        raise RuntimeError(message)

    monkeypatch.setattr(config_module, "read_secret", broken)
    error = failure_of(environ_in(tmp_path))
    assert error.variables == ("GISTING_UPSTREAM_SECRET",)
    assert "RuntimeError" in str(error)
    assert CANARY not in str(error)


def test_every_problem_is_named_in_the_order_the_variables_are_read(tmp_path: Path) -> None:
    error = failure_of({
        **environ_in(tmp_path),
        "GISTING_GIST_DIR": "~nouser-4c1e/gist",
        "GISTING_SERVE_PORT": LONG_PORT,
        "GISTING_EMAIL_SECRET": " ",
    })
    assert error.variables == ("GISTING_SERVE_PORT", "GISTING_EMAIL_SECRET", "GISTING_GIST_DIR")


@pytest.mark.parametrize(
    ("name", "value"),
    [("GISTING_SERVE_PORT", LONG_PORT), ("GISTING_MODEL_DIR", "~nouser-4c1e/models")],
)
def test_the_startup_record_carries_the_variables_for_such_errors(
    tmp_path: Path, name: str, value: str
) -> None:
    run = new_run(tmp_path)
    run.environ[name] = value
    run.start(never_models, never_lookup)
    assert run.finish() == 1
    (record,) = run.records()
    assert (record["stage"], record["error_type"], record["variables"]) == (
        "env",
        "ConfigError",
        [name],
    )
    assert port_is_free(run.port)
