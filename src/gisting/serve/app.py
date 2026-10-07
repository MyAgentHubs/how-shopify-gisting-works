import contextlib
import hmac
import json
import re
import socket
import sys
import threading
import time
from dataclasses import asdict, dataclass, field, replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import cast

from gisting.serve.config import Limits, validate_secret
from gisting.serve.contract import ErrorType, GenerateRequest, RequestRejected, decode_request
from gisting.serve.ip_digest import IP_DIGEST_HEADER, read_ip_digest
from gisting.serve.logs import LogRecord, RequestLog, failure_site
from gisting.serve.service import Handled, Refused, Served, Service
from gisting.tools.millis import round_ms

LOOPBACK = "127.0.0.1"
SECRET_HEADER = "x-gisting-upstream-secret"
JSON_TYPE = "application/json"
GENERATE = ("POST", "/generate")
HEALTH = ("GET", "/health")
BODYLESS = ("GET", "HEAD")
ASCII_DIGITS = re.compile(r"[0-9]+")
STATUS: dict[ErrorType, int] = {
    "invalid_request": 400,
    "unauthorized": 401,
    "too_long": 413,
    "compare_unavailable": 409,
    "busy": 503,
    "not_ready": 503,
    "timeout": 504,
    "internal": 500,
}
OK = 200
NOT_FOUND = 404
UNAVAILABLE = 503
SERVER_ERROR = 500


@dataclass(frozen=True)
class AppContext:
    service: Service
    logs: RequestLog
    secret: bytes = field(repr=False)
    limits: Limits


def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    keys = [key for key, _ in pairs]
    if len(set(keys)) != len(keys):
        raise ValueError
    return dict(pairs)


def parse_json(raw: bytes) -> object:
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=reject_duplicates)
    except (ValueError, RecursionError) as error:
        raise RequestRejected("invalid_request") from error


def error_document(error_type: ErrorType, retry_after_s: int | None) -> dict[str, object]:
    error: dict[str, object] = {"type": error_type}
    if retry_after_s is not None:
        error["retry_after_s"] = retry_after_s
    return {"error": error}


def rounded(value: float | None) -> float | None:
    return None if value is None else round_ms(value)


def refusal_label(refused: Refused) -> str:
    return f"internal:{refused.detail}" if refused.detail else refused.error_type


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "gisting-serve"
    sys_version = ""
    responded = False
    body_read = False

    @property
    def context(self) -> AppContext:
        return cast(ServeServer, self.server).context

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(self.context.limits.socket_timeout_s)
        self.header_timer = threading.Timer(self.context.limits.socket_timeout_s, self.cut_off)
        self.header_timer.daemon = True
        self.header_timer.start()

    def finish(self) -> None:
        self.header_timer.cancel()
        super().finish()

    def cut_off(self) -> None:
        with contextlib.suppress(OSError):
            self.connection.shutdown(socket.SHUT_RDWR)

    def log_message(self, format: str, *args: object) -> None:
        return None

    def send_error(self, code: int, message: str | None = None, explain: str | None = None) -> None:
        self.fail("invalid_request" if code < SERVER_ERROR else "internal", code)

    def handle_any(self) -> None:
        self.header_timer.cancel()
        self.close_connection = True
        try:
            self.route()
        except Exception:
            if not self.responded:
                self.fail("internal", SERVER_ERROR)
            raise
        finally:
            self.linger()

    do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = do_HEAD = do_OPTIONS = handle_any

    def route(self) -> None:
        if not self.authorized():
            self.fail("unauthorized", STATUS["unauthorized"])
        elif (self.command, self.path) == HEALTH:
            self.health()
        elif (self.command, self.path) == GENERATE:
            self.generate()
        else:
            self.fail("invalid_request", NOT_FOUND)

    def authorized(self) -> bool:
        port = cast(ServeServer, self.server).server_address[1]
        hosts = self.headers.get_all("host") or []
        secrets = self.headers.get_all(SECRET_HEADER) or []
        host_ok = hosts == [f"{LOOPBACK}:{port}"]
        supplied = secrets[0].encode("latin-1") if len(secrets) == 1 else b""
        secret_ok = hmac.compare_digest(supplied, self.context.secret) and len(secrets) == 1
        return host_ok and secret_ok

    def health(self) -> None:
        report = self.context.service.health()
        self.send_json(OK if report.status == "ready" else UNAVAILABLE, asdict(report), {})

    def generate(self) -> None:
        try:
            ip_digest = read_ip_digest(
                self.headers.get_all(IP_DIGEST_HEADER) or [], self.context.limits.ip_digest_pattern
            )
            request = decode_request(self.read_json())
        except RequestRejected as rejected:
            self.fail(rejected.error_type, STATUS[rejected.error_type])
            return
        self.answer(request, self.context.service.handle(request, ip_digest))

    def answer(self, request: GenerateRequest, handled: Handled) -> None:
        logs = self.context.logs
        base = LogRecord(
            "generate",
            session=logs.digest(request.session_id),
            mode=request.mode,
            queue_ms=rounded(handled.timing.queue_ms),
            run_ms=rounded(handled.timing.run_ms),
        )
        if handled.timing.session_reset:
            logs.emit(LogRecord("session_reset_over_limit", session=base.session, mode=base.mode))
        if isinstance(handled.result, Served):
            self.answer_served(base, handled.result)
        else:
            self.answer_refused(base, handled.result)

    def answer_served(self, base: LogRecord, served: Served) -> None:
        tokens, source, reason = served.tokens, served.reply_source, served.fallback_reason
        record = replace(
            base,
            status=OK,
            reply_source=source,
            fallback_reason=reason,
            tokens=tokens,
            lookups=served.lookups or None,
        )
        self.context.logs.emit(record)
        self.send_json(OK, {"answer": served.answer, "trace": served.trace}, {})

    def answer_refused(self, base: LogRecord, refused: Refused) -> None:
        status = STATUS[refused.error_type]
        record = replace(
            base,
            status=status,
            error_type=refusal_label(refused),
            lookups=refused.lookups or None,
        )
        self.context.logs.emit(record)
        headers: dict[str, str] = {}
        if refused.retry_after_s is not None:
            headers["retry-after"] = str(refused.retry_after_s)
        self.send_json(status, error_document(refused.error_type, refused.retry_after_s), headers)

    def fail(self, error_type: ErrorType, status: int) -> None:
        self.context.logs.emit(LogRecord("rejected", status, error_type=error_type))
        self.send_json(status, error_document(error_type, None), {})

    def send_json(self, status: int, document: object, headers: dict[str, str]) -> None:
        payload = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
        self.responded = True
        self.send_response(status)
        self.send_header("Content-Type", f"{JSON_TYPE}; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        for name, value in headers.items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(payload)

    def declared_length(self) -> int:
        lengths = self.headers.get_all("content-length") or []
        if len(lengths) != 1 or "transfer-encoding" in self.headers:
            raise RequestRejected("invalid_request")
        if ASCII_DIGITS.fullmatch(lengths[0]) is None or not lengths[0].strip("0"):
            raise RequestRejected("invalid_request")
        digits = lengths[0].lstrip("0")
        longest = len(str(self.context.limits.max_body_bytes))
        if len(digits) > longest or int(digits) > self.context.limits.max_body_bytes:
            raise RequestRejected("too_long")
        return int(digits)

    def read_json(self) -> object:
        length = self.declared_length()
        if self.headers.get_content_type() != JSON_TYPE:
            raise RequestRejected("invalid_request")
        return parse_json(self.read_exactly(length))

    def read_exactly(self, length: int) -> bytes:
        expires = time.monotonic() + self.context.limits.socket_timeout_s
        chunks: list[bytes] = []
        remaining = length
        try:
            while remaining and time.monotonic() < expires:
                chunk = self.rfile.read1(remaining)
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
        except TimeoutError as error:
            raise RequestRejected("invalid_request") from error
        if remaining:
            raise RequestRejected("invalid_request")
        self.body_read = True
        return b"".join(chunks)

    def linger(self) -> None:
        has_body_headers = "content-length" in self.headers or "transfer-encoding" in self.headers
        if self.body_read or not (has_body_headers or self.command not in BODYLESS):
            return
        expires = time.monotonic() + self.context.limits.socket_timeout_s
        budget = self.context.limits.max_body_bytes
        with contextlib.suppress(OSError):
            self.connection.shutdown(socket.SHUT_WR)
            while budget > 0 and time.monotonic() < expires:
                chunk = self.rfile.read1(budget)
                if not chunk:
                    break
                budget -= len(chunk)


class ServeServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, port: int, context: AppContext) -> None:
        super().__init__((LOOPBACK, port), Handler)
        self.context = context

    def handle_error(self, request: object, client_address: object) -> None:
        error = sys.exc_info()[1]
        record = LogRecord("error", error_type=type(error).__name__, where=failure_site(error))
        self.context.logs.emit(record)


def make_server(port: int, context: AppContext) -> ServeServer:
    validate_secret(context.secret.decode("latin-1"))
    return ServeServer(port, context)
