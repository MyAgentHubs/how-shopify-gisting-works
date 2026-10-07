from dataclasses import replace
from pathlib import Path

import pytest
from loading_support import (
    CANARY,
    GIST_COUNT,
    MANIFEST,
    StubGist,
    StubModel,
    environ_in,
    serve_env,
    stub_loader,
)
from runner_support import Plain

from gisting.model_server.config import ModelConfig
from gisting.prompt.tokenizer import PromptTokenizer
from gisting.serve.config import LIMITS, ConfigError, load_env
from gisting.serve.deadline import Deadline
from gisting.serve.loading import LoadedModel, LoadError, build_transport, load_lookup, load_models
from gisting.shopify.client import AdminClient
from gisting.shopify.http_transport import HttpConfig
from gisting.shopify.results import Result, Uncertain
from gisting.shopify.target import DEV_STORE
from gisting.shopify.transport import Request

VARIABLES = (
    "GISTING_SERVE_PORT",
    "GISTING_UPSTREAM_SECRET",
    "GISTING_EMAIL_SECRET",
    "SHOPIFY_CLIENT_SECRET",
    "GISTING_MODEL_DIR",
    "GISTING_GIST_DIR",
)


class CountingTransport:
    store = DEV_STORE

    def __init__(self) -> None:
        self.calls: list[Request] = []

    def execute(self, request: Request) -> Result:
        self.calls.append(request)
        return Uncertain("timed out")


def test_a_complete_environment_loads(tmp_path: Path) -> None:
    environ = environ_in(tmp_path)
    env = load_env(environ)
    assert (env.port, env.email_secret, env.shopify_secret) == (
        8123,
        environ["GISTING_EMAIL_SECRET"],
        environ["SHOPIFY_CLIENT_SECRET"],
    )
    assert (env.model_dir, env.gist_dir) == (
        Path(environ["GISTING_MODEL_DIR"]),
        Path(environ["GISTING_GIST_DIR"]),
    )


@pytest.mark.parametrize("name", VARIABLES)
def test_a_missing_variable_is_named_and_no_value_leaks(tmp_path: Path, name: str) -> None:
    environ = environ_in(tmp_path)
    del environ[name]
    with pytest.raises(ConfigError) as caught:
        load_env(environ)
    assert name in str(caught.value)
    assert CANARY not in str(caught.value)


def test_every_missing_variable_is_listed_at_once() -> None:
    with pytest.raises(ConfigError) as caught:
        load_env({})
    assert all(name in str(caught.value) for name in VARIABLES)


def test_two_bad_values_are_both_reported_without_echoing_them(tmp_path: Path) -> None:
    environ = environ_in(tmp_path)
    environ["GISTING_MODEL_DIR"] = str(tmp_path / f"{CANARY}-absent")
    environ["GISTING_EMAIL_SECRET"] = ""
    with pytest.raises(ConfigError) as caught:
        load_env(environ)
    message = str(caught.value)
    assert "GISTING_MODEL_DIR" in message
    assert "GISTING_EMAIL_SECRET" in message
    assert "GISTING_GIST_DIR" not in message
    assert CANARY not in message


def test_a_file_in_place_of_a_directory_is_refused(tmp_path: Path) -> None:
    environ = environ_in(tmp_path)
    plain = tmp_path / "plain-file"
    plain.write_text("x", encoding="utf-8")
    environ["GISTING_GIST_DIR"] = str(plain)
    with pytest.raises(ConfigError, match="GISTING_GIST_DIR"):
        load_env(environ)


def test_the_device_is_optional_and_blank_means_automatic(tmp_path: Path) -> None:
    environ = environ_in(tmp_path)
    assert load_env(environ).device is None
    assert load_env({**environ, "GISTING_DEVICE": "  "}).device is None
    assert load_env({**environ, "GISTING_DEVICE": "cpu"}).device == "cpu"


def test_the_configured_device_reaches_the_model_loader(tmp_path: Path) -> None:
    seen: list[ModelConfig] = []
    model = StubModel(gist=StubGist(), gist_manifest=MANIFEST)

    def load(config: ModelConfig) -> tuple[LoadedModel, PromptTokenizer]:
        seen.append(config)
        return stub_loader(model)(config)

    env = replace(serve_env(tmp_path), device="cpu")
    load_models(env, load)
    assert [(config.device, config.model_dir, config.gist_dir) for config in seen] == [
        ("cpu", env.model_dir, env.gist_dir)
    ]


def test_the_shopify_limits_are_the_agreed_defaults() -> None:
    assert (LIMITS.shopify_timeout_s, LIMITS.shopify_read_attempts) == (6.0, 2)
    assert LIMITS.shopify_retry_s == 0.5
    assert LIMITS.shopify_max_pause_s == 2.0


def test_the_transport_takes_its_limits_from_the_data_file() -> None:
    seen: list[tuple[str, HttpConfig]] = []
    inner = Plain(CountingTransport())

    def make(secret: str, config: HttpConfig) -> Plain:
        seen.append((secret, config))
        return inner

    assert build_transport("s3cret", LIMITS, make) is inner
    assert seen == [
        (
            "s3cret",
            HttpConfig(
                timeout=LIMITS.shopify_timeout_s,
                query_attempts=1,
                max_wait_seconds=LIMITS.shopify_max_pause_s,
            ),
        )
    ]


def test_the_client_is_read_only_and_retries_as_often_as_the_limit_allows(tmp_path: Path) -> None:
    counting = CountingTransport()
    sleeps: list[float] = []
    parts = load_lookup(
        serve_env(tmp_path), LIMITS, lambda _secret, _config: Plain(counting), sleeps.append
    )
    client = parts.client_for(Deadline(1000.0, lambda: 0.0))
    assert isinstance(client, AdminClient)
    client.fetch_order("#1042")
    assert len(counting.calls) == LIMITS.shopify_read_attempts
    assert sleeps == [LIMITS.shopify_retry_s] * (LIMITS.shopify_read_attempts - 1)
    assert parts.email_secret == "email-secret"
    assert parts.policy.cache_ttl_seconds > 0


def test_shopify_assembly_errors_carry_only_the_type_name(tmp_path: Path) -> None:
    def broken(secret: str, config: HttpConfig) -> Plain:
        message = f"{CANARY} {secret} {config}"
        raise RuntimeError(message)

    with pytest.raises(LoadError) as caught:
        load_lookup(serve_env(tmp_path), LIMITS, broken)
    assert "RuntimeError" in str(caught.value)
    assert CANARY not in str(caught.value)
    assert "shopify-secret" not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__suppress_context__


def test_one_model_serves_both_modes_and_only_the_gist_one_carries_the_gist(
    tmp_path: Path,
) -> None:
    model = StubModel(gist=StubGist(), gist_manifest=MANIFEST)
    gist, full = load_models(serve_env(tmp_path), stub_loader(model))
    assert (gist.model, gist.gist_count, gist.gist_run_id) == (model, GIST_COUNT, "run-1")
    assert (full.gist_count, full.gist_run_id) == (None, None)
    assert isinstance(full.model, StubModel)
    assert full.model.gist is None
    assert gist.tokenizer is full.tokenizer
    assert "gist" in gist.identity
    assert "gist" not in full.identity


def test_a_missing_gist_artifact_is_refused(tmp_path: Path) -> None:
    with pytest.raises(LoadError, match="gist"):
        load_models(serve_env(tmp_path), stub_loader(StubModel()))


def test_a_load_failure_carries_only_the_type_name(tmp_path: Path) -> None:
    def failing(config: ModelConfig) -> tuple[LoadedModel, PromptTokenizer]:
        message = f"{CANARY} {config.model_dir}"
        raise OSError(message)

    with pytest.raises(LoadError) as caught:
        load_models(serve_env(tmp_path), failing)
    assert "OSError" in str(caught.value)
    assert CANARY not in str(caught.value)
    assert str(tmp_path) not in str(caught.value)
    assert caught.value.__suppress_context__
