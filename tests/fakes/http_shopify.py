import json
import threading
import time
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

from gisting.shopify.jsonvalue import Json

DEFAULT_BODY: Json = {"data": {"shop": {"name": "fake"}}}


@dataclass
class Canned:
    status: int = 200
    body: Json = field(default_factory=lambda: DEFAULT_BODY)
    headers: dict[str, str] = field(default_factory=lambda: {})
    raw: bytes | None = None


class Drop:
    pass


@dataclass
class Stall:
    seconds: float


@dataclass
class Drip:
    interval: float
    count: int
    declared: int | None = None
    status: int = 200
    in_headers: bool = False


Step = Canned | Drop | Stall | Drip


@dataclass
class Seen:
    path: str
    headers: dict[str, str]
    body: bytes


class FakeShopify:
    def __init__(self, expires_in: int = 86399) -> None:
        self.expires_in = expires_in
        self.valid_token = ""
        self.issued = 0
        self.token_status = 200
        self.reject_all = False
        self.token_calls: list[Seen] = []
        self.graphql_calls: list[Seen] = []
        self.script: list[Step] = []
        self.lock = threading.Lock()

    def issue(self) -> str:
        self.issued += 1
        self.valid_token = f"fake-token-{self.issued}"
        return self.valid_token

    def revoke(self) -> None:
        self.valid_token = ""


class ShopServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, shop: FakeShopify) -> None:
        super().__init__(("127.0.0.1", 0), ShopHandler)
        self.shop = shop


class ShopHandler(BaseHTTPRequestHandler):
    @property
    def shop(self) -> FakeShopify:
        assert isinstance(self.server, ShopServer)
        return self.server.shop

    def log_message(self, format: str, *args: object) -> None:
        return

    def reply(self, status: int, body: bytes, headers: dict[str, str]) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for key, value in headers.items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        seen = Seen(self.path, dict(self.headers.items()), self.rfile.read(length))
        if self.path.endswith("/oauth/access_token"):
            self.token(seen)
        else:
            self.graphql(seen)

    def token(self, seen: Seen) -> None:
        shop = self.shop
        with shop.lock:
            shop.token_calls.append(seen)
            status = shop.token_status
            token = shop.issue() if status == 200 else ""
        payload: Json = {"access_token": token, "expires_in": shop.expires_in, "scope": "x"}
        if status != 200:
            payload = {"error": "invalid_client"}
        self.reply(status, json.dumps(payload).encode(), {})

    def authorized(self, seen: Seen) -> bool:
        shop = self.shop
        return (
            not shop.reject_all and seen.headers.get("X-Shopify-Access-Token") == shop.valid_token
        )

    def drip(self, step: Drip) -> None:
        declared = step.count if step.declared is None else step.declared
        self.close_connection = True
        try:
            if step.in_headers:
                self.drip_headers(step)
            else:
                self.drip_body(step, declared)
        except OSError:
            return

    def drip_headers(self, step: Drip) -> None:
        self.wfile.write(b"HTTP/1.1 200 Fake\r\n")
        for index in range(step.count):
            self.wfile.write(f"X-Drip-{index}: 1\r\n".encode())
            self.wfile.flush()
            time.sleep(step.interval)
        self.wfile.write(b"Content-Length: 0\r\n\r\n")

    def drip_body(self, step: Drip, declared: int) -> None:
        self.send_response(step.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(declared))
        self.end_headers()
        for _ in range(step.count):
            self.wfile.write(b" ")
            self.wfile.flush()
            time.sleep(step.interval)

    def graphql(self, seen: Seen) -> None:
        shop = self.shop
        with shop.lock:
            shop.graphql_calls.append(seen)
            step = shop.script.pop(0) if shop.script else Canned()
        if not self.authorized(seen):
            self.reply(401, b'{"errors":"unauthorized"}', {})
        elif isinstance(step, Drop):
            self.close_connection = True
            self.connection.close()
        elif isinstance(step, Stall):
            time.sleep(step.seconds)
            self.reply(200, b"{}", {})
        elif isinstance(step, Drip):
            self.drip(step)
        else:
            raw = step.raw if step.raw is not None else json.dumps(step.body).encode()
            self.reply(step.status, raw, step.headers)


@contextmanager
def running_shop(expires_in: int = 86399) -> Generator[tuple[FakeShopify, str]]:
    shop = FakeShopify(expires_in)
    server = ShopServer(shop)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield shop, f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def form_fields(body: bytes) -> dict[str, str]:
    return {key: values[0] for key, values in parse_qs(body.decode()).items()}
