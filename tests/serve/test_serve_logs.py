import io
import json
from pathlib import Path

import pytest
from loading_support import environ_in

from gisting.serve.config import LIMITS, ConfigError, load_env
from gisting.serve.logs import LogRecord, RequestLog, degraded_logger

KEY = b"k" * 32
GOOD_SECRET = "s3cret-value-" + "x" * 24


def make_log(stream: io.StringIO, key: bytes = KEY) -> RequestLog:
    return RequestLog(stream, lambda: 1_700_000_000.5, key)


def test_one_json_line_per_record_with_only_the_set_fields() -> None:
    stream = io.StringIO()
    log = make_log(stream)
    log.emit(LogRecord("generate", 200, mode="gist", queue_ms=1.5, run_ms=20.0, tokens=321))
    lines = stream.getvalue().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0]) == {
        "ts": "2023-11-14T22:13:20.500Z",
        "event": "generate",
        "status": 200,
        "mode": "gist",
        "queue_ms": 1.5,
        "run_ms": 20.0,
        "tokens": 321,
    }


def test_the_record_type_has_no_field_for_text() -> None:
    allowed = {
        "event",
        "status",
        "session",
        "mode",
        "queue_ms",
        "run_ms",
        "reply_source",
        "fallback_reason",
        "tokens",
        "error_type",
        "inner_type",
        "thread",
        "where",
        "stage",
        "variables",
        "lookups",
    }
    assert set(LogRecord.__dataclass_fields__) == allowed


def test_session_digest_is_eight_hex_keyed_and_stable() -> None:
    first = make_log(io.StringIO()).digest("session-abcdef")
    assert len(first) == 8
    int(first, 16)
    assert make_log(io.StringIO()).digest("session-abcdef") == first
    assert make_log(io.StringIO(), b"z" * 32).digest("session-abcdef") != first
    assert "session-abcdef" not in first


def test_each_process_gets_its_own_random_key() -> None:
    one = RequestLog(io.StringIO()).digest("same-session")
    other = RequestLog(io.StringIO()).digest("same-session")
    assert one != other


def test_the_minimum_secret_length_comes_from_the_data_file(tmp_path: Path) -> None:
    assert LIMITS.min_secret_chars >= 32
    exact = "x" * LIMITS.min_secret_chars
    env = load_env({**environ_in(tmp_path), "GISTING_UPSTREAM_SECRET": exact})
    assert env.upstream_secret == exact


def test_env_requires_port_and_secret(tmp_path: Path) -> None:
    env = load_env({
        **environ_in(tmp_path),
        "GISTING_SERVE_PORT": "8123",
        "GISTING_UPSTREAM_SECRET": GOOD_SECRET,
    })
    assert env.port == 8123
    assert env.upstream_secret == GOOD_SECRET


@pytest.mark.parametrize(
    "environ",
    [
        {"GISTING_SERVE_PORT": "8123", "GISTING_UPSTREAM_SECRET": ""},
        {"GISTING_SERVE_PORT": "8123", "GISTING_UPSTREAM_SECRET": "   "},
        {"GISTING_SERVE_PORT": "8123", "GISTING_UPSTREAM_SECRET": "sécret" + "x" * 30},
        {"GISTING_SERVE_PORT": "8123", "GISTING_UPSTREAM_SECRET": "short-secret"},
        {"GISTING_SERVE_PORT": "8123", "GISTING_UPSTREAM_SECRET": "x" * 31},
        {"GISTING_SERVE_PORT": "8123", "GISTING_UPSTREAM_SECRET": " " + "x" * 40},
        {"GISTING_SERVE_PORT": "8123", "GISTING_UPSTREAM_SECRET": "x" * 40 + "\n"},
        {"GISTING_SERVE_PORT": "8123", "GISTING_UPSTREAM_SECRET": "x" * 20 + "\t" + "x" * 20},
        {"GISTING_SERVE_PORT": "abc", "GISTING_UPSTREAM_SECRET": GOOD_SECRET},
        {"GISTING_SERVE_PORT": "0", "GISTING_UPSTREAM_SECRET": GOOD_SECRET},
        {"GISTING_SERVE_PORT": "70000", "GISTING_UPSTREAM_SECRET": GOOD_SECRET},
    ],
)
def test_bad_env_fails_loudly_without_echoing_values(
    environ: dict[str, str], tmp_path: Path
) -> None:
    with pytest.raises(ConfigError) as caught:
        load_env({**environ_in(tmp_path), **environ})
    for value in environ.values():
        assert not value.strip() or value not in str(caught.value)


@pytest.mark.parametrize("name", ["GISTING_SERVE_PORT", "GISTING_UPSTREAM_SECRET"])
def test_a_missing_port_or_secret_fails_loudly(name: str, tmp_path: Path) -> None:
    environ = environ_in(tmp_path)
    del environ[name]
    with pytest.raises(ConfigError, match=name):
        load_env(environ)


def test_the_degraded_logger_writes_the_reason_code_and_nothing_else() -> None:
    stream = io.StringIO()
    degraded_logger(make_log(stream))("failure_store_evicted")
    assert json.loads(stream.getvalue()) == {
        "ts": "2023-11-14T22:13:20.500Z",
        "event": "degraded",
        "fallback_reason": "failure_store_evicted",
    }
