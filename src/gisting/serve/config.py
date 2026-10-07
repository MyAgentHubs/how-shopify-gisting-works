import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import cast, get_type_hints

LIMITS_FILE = Path(__file__).resolve().parents[3] / "data" / "serve" / "limits.json"
WORD_BREAK = re.compile(r"(?<!^)(?=[A-Z])")


class ConfigError(ValueError):
    def __init__(self, message: str, variables: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.variables = variables


@dataclass(frozen=True)
class Limits:
    max_message_chars: int
    session_id_pattern: str
    session_id_max_chars: int
    max_body_bytes: int
    socket_timeout_s: float
    session_ttl_s: float
    max_sessions: int
    max_turns_per_session: int
    max_session_bytes: int
    max_waiting: int
    total_deadline_s: float
    retry_after_s: int
    min_secret_chars: int
    ip_failure_limit: int
    failure_ttl_s: float
    max_failure_keys: int
    ip_digest_pattern: str
    shopify_timeout_s: float
    shopify_read_attempts: int
    shopify_retry_s: float
    shopify_max_pause_s: float


def snake_case(name: str) -> str:
    return WORD_BREAK.sub("_", name).lower()


def checked(name: str, expected: object, value: object) -> object:
    if expected is str:
        if isinstance(value, str) and value:
            return value
    elif expected is int:
        if type(value) is int and value > 0:
            return value
    elif type(value) in (int, float) and isinstance(value, int | float) and value > 0:
        return float(value)
    message = f"{name} must be a positive {getattr(expected, '__name__', expected)}"
    raise ConfigError(message)


def read_document(path: Path) -> dict[str, object]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        message = f"cannot read {path.name}: {type(error).__name__}"
        raise ConfigError(message) from error
    if not isinstance(document, dict):
        message = f"{path.name} must hold a JSON object"
        raise ConfigError(message)
    entries = cast(dict[str, object], document)
    return {snake_case(key): value for key, value in entries.items()}


def load_limits(path: Path = LIMITS_FILE) -> Limits:
    document = read_document(path)
    hints = get_type_hints(Limits)
    names = [field.name for field in fields(Limits)]
    if set(document) != set(names):
        message = (
            f"{path.name} keys differ from the expected set: {sorted(set(document) ^ set(names))}"
        )
        raise ConfigError(message)
    values = {name: checked(name, hints[name], document[name]) for name in names}
    limits = Limits(**values)  # type: ignore[arg-type]
    for name in ("session_id_pattern", "ip_digest_pattern"):
        try:
            re.compile(getattr(limits, name))
        except re.error as error:
            message = f"{name} is not a regular expression"
            raise ConfigError(message) from error
    return limits


LIMITS = load_limits()
PORT_VARIABLE = "GISTING_SERVE_PORT"
SECRET_VARIABLE = "GISTING_UPSTREAM_SECRET"
EMAIL_SECRET_VARIABLE = "GISTING_EMAIL_SECRET"
SHOPIFY_SECRET_VARIABLE = "SHOPIFY_CLIENT_SECRET"
MODEL_DIR_VARIABLE = "GISTING_MODEL_DIR"
GIST_DIR_VARIABLE = "GISTING_GIST_DIR"
DEVICE_VARIABLE = "GISTING_DEVICE"
MAX_PORT = 65535
PORT_DIGITS = len(str(MAX_PORT))


@dataclass(frozen=True)
class ServeEnv:
    port: int
    upstream_secret: str = field(repr=False)
    email_secret: str = field(repr=False)
    shopify_secret: str = field(repr=False)
    model_dir: Path
    gist_dir: Path
    device: str | None = None


def read_port(environ: Mapping[str, str]) -> int:
    raw = environ.get("GISTING_SERVE_PORT", "")
    digits = raw.isascii() and raw.isdecimal() and len(raw) <= PORT_DIGITS
    if not digits or not 1 <= int(raw) <= MAX_PORT:
        message = f"{PORT_VARIABLE} must be an integer from 1 to {MAX_PORT}"
        raise ConfigError(message, (PORT_VARIABLE,))
    return int(raw)


def validate_secret(secret: str, name: str = SECRET_VARIABLE) -> str:
    plain = secret.isascii() and secret.isprintable() and secret == secret.strip()
    if not plain or len(secret) < LIMITS.min_secret_chars:
        message = (
            f"{name} must be printable ASCII without edge spaces, "
            f"at least {LIMITS.min_secret_chars} characters"
        )
        raise ConfigError(message, (name,))
    return secret


def read_secret(environ: Mapping[str, str]) -> str:
    return validate_secret(environ.get("GISTING_UPSTREAM_SECRET", ""))


def read_email_secret(environ: Mapping[str, str]) -> str:
    return validate_secret(environ.get("GISTING_EMAIL_SECRET", ""), EMAIL_SECRET_VARIABLE)


def read_present(environ: Mapping[str, str], name: str) -> str:
    value = environ.get(name, "")
    if not value.strip():
        message = f"{name} must be set"
        raise ConfigError(message, (name,))
    return value


def is_directory(path: Path) -> bool:
    try:
        return path.expanduser().is_dir()
    except (OSError, RuntimeError):
        return False


def read_directory(environ: Mapping[str, str], name: str) -> Path:
    path = Path(read_present(environ, name))
    if not is_directory(path):
        message = f"{name} must name an existing directory"
        raise ConfigError(message, (name,))
    return path.expanduser()


def read_device(environ: Mapping[str, str]) -> str | None:
    return environ.get(DEVICE_VARIABLE, "").strip() or None


def collect_problems(environ: Mapping[str, str]) -> list[ConfigError]:
    readers: list[tuple[str, Callable[[], object]]] = [
        (PORT_VARIABLE, lambda: read_port(environ)),
        (SECRET_VARIABLE, lambda: read_secret(environ)),
        (EMAIL_SECRET_VARIABLE, lambda: read_email_secret(environ)),
        (SHOPIFY_SECRET_VARIABLE, lambda: read_present(environ, SHOPIFY_SECRET_VARIABLE)),
        (MODEL_DIR_VARIABLE, lambda: read_directory(environ, MODEL_DIR_VARIABLE)),
        (GIST_DIR_VARIABLE, lambda: read_directory(environ, GIST_DIR_VARIABLE)),
    ]
    problems: list[ConfigError] = []
    for name, read in readers:
        try:
            read()
        except ConfigError as error:
            problems.append(error)
        except Exception as error:  # noqa: BLE001
            message = f"{name} could not be read: {type(error).__name__}"
            problems.append(ConfigError(message, (name,)))
    return problems


def load_env(environ: Mapping[str, str]) -> ServeEnv:
    problems = collect_problems(environ)
    if problems:
        variables = tuple(name for problem in problems for name in problem.variables)
        raise ConfigError("; ".join(str(problem) for problem in problems), variables)
    return ServeEnv(
        read_port(environ),
        read_secret(environ),
        read_email_secret(environ),
        read_present(environ, SHOPIFY_SECRET_VARIABLE),
        read_directory(environ, MODEL_DIR_VARIABLE),
        read_directory(environ, GIST_DIR_VARIABLE),
        read_device(environ),
    )
