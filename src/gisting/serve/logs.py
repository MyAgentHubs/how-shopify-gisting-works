import hashlib
import hmac
import json
import secrets
import threading
import time
import traceback
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TextIO

from gisting.tools.reads import LookupRead

DIGEST_HEX_CHARS = 8
KEY_BYTES = 32


@dataclass(frozen=True)
class LogRecord:
    event: str
    status: int | None = None
    session: str | None = None
    mode: str | None = None
    queue_ms: float | None = None
    run_ms: float | None = None
    reply_source: str | None = None
    fallback_reason: str | None = None
    tokens: int | None = None
    error_type: str | None = None
    inner_type: str | None = None
    thread: str | None = None
    where: str | None = None
    stage: str | None = None
    variables: tuple[str, ...] | None = None
    lookups: tuple[LookupRead, ...] | None = None


def failure_site(error: BaseException | None) -> str | None:
    if error is None or error.__traceback__ is None:
        return None
    last = traceback.extract_tb(error.__traceback__)[-1]
    return f"{Path(last.filename).name}:{last.name}:{last.lineno}"


class RequestLog:
    def __init__(
        self,
        stream: TextIO,
        clock: Callable[[], float] = time.time,
        key: bytes | None = None,
    ) -> None:
        self._stream = stream
        self._clock = clock
        self._key = key or secrets.token_bytes(KEY_BYTES)
        self._lock = threading.Lock()

    def digest(self, session_id: str) -> str:
        mac = hmac.new(self._key, session_id.encode(), hashlib.sha256)
        return mac.hexdigest()[:DIGEST_HEX_CHARS]

    def emit(self, record: LogRecord) -> None:
        stamp = datetime.fromtimestamp(self._clock(), UTC).isoformat(timespec="milliseconds")
        fields = {name: value for name, value in asdict(record).items() if value is not None}
        line = json.dumps({"ts": stamp.replace("+00:00", "Z"), **fields}, sort_keys=True)
        with self._lock:
            self._stream.write(line + "\n")
            self._stream.flush()


def degraded_logger(logs: RequestLog) -> Callable[[str], None]:
    def report(reason: str) -> None:
        logs.emit(LogRecord("degraded", fallback_reason=reason))

    return report
